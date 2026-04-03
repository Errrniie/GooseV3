#!/usr/bin/env python3

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

import numpy as np
import cv2
import time

from ultralytics import YOLO

model = YOLO("yolov8n.pt")

Gst.init(None)

LAPTOP_IP = "192.168.8.154"
PORT = 5000

PIPELINE = f"""
nvarguscamerasrc !
video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1 !
tee name=t

t. ! queue leaky=2 max-size-buffers=2 !
nvvidconv ! video/x-raw,format=BGRx !
videoconvert ! video/x-raw,format=BGR !
appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false

t. ! queue leaky=2 max-size-buffers=2 !
nvvidconv ! video/x-raw,format=I420 !
x264enc tune=zerolatency speed-preset=ultrafast bitrate=3000 key-int-max=15 !
rtph264pay config-interval=1 pt=96 !
udpsink host={LAPTOP_IP} port={PORT} sync=false
"""

class CameraApp:
    def __init__(self):
        self.pipeline = Gst.parse_launch(PIPELINE)
        self.appsink = self.pipeline.get_by_name("sink")

        self.appsink.connect("new-sample", self.on_frame)

        self.frame_count = 0
        self.start_time = time.time()

    def on_frame(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        caps = sample.get_caps()

        width = caps.get_structure(0).get_value("width")
        height = caps.get_structure(0).get_value("height")

        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR

        frame = np.frombuffer(map_info.data, np.uint8)
        frame = frame.reshape((height, width, 3)).copy()

        buf.unmap(map_info)

        self.frame_count += 1
        if self.frame_count % 2 == 0:  # start with half rate
            results = model(frame, verbose=False)

            for r in results:
                boxes = r.boxes
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # ---- FPS TRACK ----
        if self.frame_count % 30 == 0:
            elapsed = time.time() - self.start_time
            fps = self.frame_count / elapsed
            print(f"[INFO] FPS: {fps:.2f}")

        return Gst.FlowReturn.OK

    def run(self):
        print("[INFO] Starting pipeline...")
        self.pipeline.set_state(Gst.State.PLAYING)

        loop = GLib.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            print("\n[INFO] Stopping...")
            pass

        self.pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    app = CameraApp()
    app.run()