#!/usr/bin/env python3
"""
Distance Estimation Test - Interactive point selection for distance calibration.

This script:
1. Starts camera and broadcasts video stream
2. Receives click coordinates from laptop web interface
3. Displays received coordinates for distance estimation calibration

Usage:
    python3 distance_estimation_test.py

On your laptop, open the provided HTML file to view the stream and click points.
"""

import sys
import os
import time
import threading
import uvicorn

# Add project root to Python path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from Domains.Vision.Interface import start_vision, stop_vision
import Config.Network_Config as net_cfg

# FastAPI app for receiving coordinates
app = FastAPI(title="Distance Estimation Test")

# Store received coordinates
received_points = []
_points_lock = threading.Lock()


class ClickPoint(BaseModel):
    """Click point data from laptop."""
    x: int
    y: int
    timestamp: float = None


@app.post("/click")
async def receive_click(point: ClickPoint):
    """
    Receive click coordinates from laptop web interface.
    
    Args:
        point: ClickPoint with x, y coordinates and optional timestamp
    
    Returns:
        JSON confirmation
    """
    if point.timestamp is None:
        point.timestamp = time.time()
    
    with _points_lock:
        received_points.append({
            "x": point.x,
            "y": point.y,
            "timestamp": point.timestamp
        })
    
    print(f"[CLICK] Received point: ({point.x}, {point.y}) at {point.timestamp:.3f}")
    return {"status": "received", "point": {"x": point.x, "y": point.y}}


@app.get("/points")
async def get_points():
    """Get all received click points."""
    with _points_lock:
        return {"points": received_points.copy()}


@app.delete("/points")
async def clear_points():
    """Clear all received points."""
    with _points_lock:
        count = len(received_points)
        received_points.clear()
    print(f"[CLICK] Cleared {count} points")
    return {"status": "cleared", "count": count}


@app.get("/video")
async def video_stream():
    """MJPEG video stream endpoint."""
    import cv2
    
    def video_generator():
        frame_count = 0
        while True:
            try:
                from Domains.Vision.Interface import camera as yolo_camera
                if yolo_camera is None:
                    time.sleep(0.1)
                    continue
                
                frame = yolo_camera.get_frame()
                if frame is None:
                    time.sleep(0.033)
                    continue
                
                # Encode frame as JPEG
                ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ok:
                    time.sleep(0.033)
                    continue
                
                frame_count += 1
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
                )
                time.sleep(0.033)  # ~30 FPS
            except Exception as e:
                print(f"[VIDEO] Error in stream: {e}")
                time.sleep(0.1)
    
    return StreamingResponse(
        video_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/")
async def root():
    """Serve the HTML interface."""
    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Distance Estimation - Click Points</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background: #1a1a1a;
            color: #fff;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: #4CAF50;
        }
        #video-container {
            position: relative;
            display: inline-block;
            border: 2px solid #4CAF50;
            background: #000;
        }
        #video-stream {
            display: block;
            max-width: 100%;
            height: auto;
        }
        .info {
            margin: 20px 0;
            padding: 15px;
            background: #2a2a2a;
            border-radius: 5px;
        }
        .points-list {
            margin-top: 20px;
            max-height: 300px;
            overflow-y: auto;
        }
        .point-item {
            padding: 5px;
            margin: 5px 0;
            background: #333;
            border-left: 3px solid #4CAF50;
        }
        button {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 10px 20px;
            margin: 5px;
            cursor: pointer;
            border-radius: 3px;
            font-size: 14px;
        }
        button:hover {
            background: #45a049;
        }
        button.danger {
            background: #f44336;
        }
        button.danger:hover {
            background: #da190b;
        }
        .status {
            margin: 10px 0;
            padding: 10px;
            border-radius: 3px;
        }
        .status.success {
            background: #4CAF50;
        }
        .status.error {
            background: #f44336;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Distance Estimation - Point Selection</h1>
        
        <div class="info">
            <p><strong>Instructions:</strong></p>
            <ol>
                <li>Click anywhere on the video feed to mark a point</li>
                <li>Each click sends coordinates to the Jetson</li>
                <li>Use "Clear Points" to reset the list</li>
            </ol>
        </div>
        
        <div id="video-container">
            <img id="video-stream" src="/video" alt="Video Stream" />
            <div id="click-overlay" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; cursor: crosshair;"></div>
        </div>
        
        <div class="info">
            <button onclick="clearPoints()">Clear Points</button>
            <button onclick="refreshVideo()">Refresh Video</button>
            <div id="status"></div>
        </div>
        
        <div class="info">
            <h3>Received Points:</h3>
            <div id="points-list" class="points-list"></div>
        </div>
    </div>
    
    <script>
        const videoContainer = document.getElementById('video-container');
        const clickOverlay = document.getElementById('click-overlay');
        const videoStream = document.getElementById('video-stream');
        const pointsList = document.getElementById('points-list');
        const statusDiv = document.getElementById('status');
        
        let points = [];
        
        // Handle clicks on the video
        clickOverlay.addEventListener('click', async (e) => {
            const rect = videoStream.getBoundingClientRect();
            const containerRect = videoContainer.getBoundingClientRect();
            
            // Calculate click position relative to video element
            const x = Math.round(e.clientX - rect.left);
            const y = Math.round(e.clientY - rect.top);
            
            // Get actual video dimensions
            const videoWidth = videoStream.naturalWidth || videoStream.width;
            const videoHeight = videoStream.naturalHeight || videoStream.height;
            
            // Scale coordinates to actual video resolution
            const scaleX = videoWidth / rect.width;
            const scaleY = videoHeight / rect.height;
            
            const scaledX = Math.round(x * scaleX);
            const scaledY = Math.round(y * scaleY);
            
            // Send to Jetson
            try {
                const response = await fetch('/click', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        x: scaledX,
                        y: scaledY,
                        timestamp: Date.now() / 1000.0
                    })
                });
                
                if (response.ok) {
                    const data = await response.json();
                    showStatus(`Point sent: (${scaledX}, ${scaledY})`, 'success');
                    addPointToList(scaledX, scaledY);
                } else {
                    showStatus('Failed to send point', 'error');
                }
            } catch (error) {
                console.error('Error sending point:', error);
                showStatus('Error sending point: ' + error.message, 'error');
            }
        });
        
        function addPointToList(x, y) {
            points.push({x, y, time: new Date().toLocaleTimeString()});
            updatePointsList();
        }
        
        function updatePointsList() {
            pointsList.innerHTML = points.map((p, i) => 
                `<div class="point-item">#${i+1}: (${p.x}, ${p.y}) at ${p.time}</div>`
            ).join('');
        }
        
        async function clearPoints() {
            try {
                const response = await fetch('/points', {
                    method: 'DELETE'
                });
                if (response.ok) {
                    points = [];
                    updatePointsList();
                    showStatus('Points cleared', 'success');
                }
            } catch (error) {
                showStatus('Error clearing points: ' + error.message, 'error');
            }
        }
        
        function refreshVideo() {
            videoStream.src = '/video?t=' + Date.now();
            showStatus('Video refreshed', 'success');
        }
        
        function showStatus(message, type) {
            statusDiv.textContent = message;
            statusDiv.className = 'status ' + type;
            setTimeout(() => {
                statusDiv.textContent = '';
                statusDiv.className = '';
            }, 3000);
        }
        
        // Periodically update points list from server
        setInterval(async () => {
            try {
                const response = await fetch('/points');
                if (response.ok) {
                    const data = await response.json();
                    if (data.points.length !== points.length) {
                        points = data.points.map(p => ({
                            x: p.x,
                            y: p.y,
                            time: new Date(p.timestamp * 1000).toLocaleTimeString()
                        }));
                        updatePointsList();
                    }
                }
            } catch (error) {
                // Silently fail - server might not be ready
            }
        }, 1000);
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


def main():
    """Main function."""
    print("\n" + "=" * 60)
    print("Distance Estimation Test")
    print("=" * 60)
    
    # Get Jetson IP address
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        jetson_ip = s.getsockname()[0]
        s.close()
    except Exception:
        jetson_ip = "localhost"
    
    # Start vision system (camera + streaming)
    print("\n[INIT] Starting vision system...")
    if net_cfg.LAPTOP_IP is not None:
        print(f"[INIT] UDP video streaming will start automatically to {net_cfg.LAPTOP_IP}:{net_cfg.STREAM_PORT}")
    start_vision()
    time.sleep(1.0)  # Let camera initialize
    
    print("\n[INIT] Starting FastAPI server on 0.0.0.0:8001")
    print("[INIT] Open in your browser:")
    print(f"  http://{jetson_ip}:8001/")
    print("\n[INIT] Endpoints:")
    print("  GET  /          - Web interface for clicking points")
    print("  POST /click     - Receive click coordinates")
    print("  GET  /points    - Get all received points")
    print("  DELETE /points  - Clear all points")
    print("\nPress Ctrl+C to stop.\n")
    
    try:
        uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping...")
    finally:
        stop_vision()
        print("[SHUTDOWN] Vision system stopped")
        print("[SHUTDOWN] Total points received:", len(received_points))
        if received_points:
            print("\n[SHUTDOWN] Points received:")
            for i, point in enumerate(received_points):
                print(f"  {i+1}. ({point['x']}, {point['y']})")


if __name__ == "__main__":
    main()
