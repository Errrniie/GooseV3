# Distance/DistanceFromJSON.py

def distance_from_y(y_pixel, calibration):
    """
    calibration: list of (y_pixel, distance_ft)
    Returns interpolated distance in feet.
    """

    # Sort by y descending (closest first)
    calib = sorted(calibration, key=lambda p: p[0], reverse=True)

    # Clamp outside range
    if y_pixel >= calib[0][0]:
        return calib[0][1]
    if y_pixel <= calib[-1][0]:
        return calib[-1][1]

    # Find enclosing interval
    for (y1, d1), (y2, d2) in zip(calib, calib[1:]):
        if y1 >= y_pixel >= y2:
            t = (y_pixel - y2) / (y1 - y2)
            return d2 + t * (d1 - d2)

    # Should never reach here
    return calib[-1][1]
