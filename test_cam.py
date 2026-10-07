"""
==============================================================
 Project Veronica - Hardware Optical Diagnostics (test_cam.py)
 Tests 4K resolution capture, MJPEG negotiation, and frame delivery
==============================================================
"""
import cv2
import time
import os

# Prevent Wayland / Qt platform display errors on Raspberry Pi OS (Bookworm)
os.environ["QT_QPA_PLATFORM"] = "xcb"

def run_camera_test():
    print("=" * 60)
    print("🔍 PROJECT VERONICA: OPTICAL SUBSYSTEM SELF-TEST")
    print("=" * 60)

    # Initialize video capture interface on device index 0
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

    # Force MJPG compression to unlock 4K @ 30 FPS across USB 3.0
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Allow optical sensor exposure and auto-white-balance to settle
    time.sleep(1.5)

    if not cap.isOpened():
        print("❌ ERROR: Could not open video device /dev/video0.")
        print("Ensure the Kreo Owl 4K camera is connected to a Blue USB 3.0 port.")
        return

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)

    print(f"📡 Sensor Stream Negotiated: {actual_w}x{actual_h} @ {actual_fps} FPS")

    if actual_w == 3840 and actual_h == 2160:
        print("✅ Native 4K UHD Mode Confirmed.")
    else:
        print(f"⚠️ Notice: Camera defaulted to {actual_w}x{actual_h}. Verify USB throughput.")

    print("\nSnapping test verification frame...")
    ret, frame = cap.read()

    if ret and frame is not None:
        test_filename = "camera_test_output.jpg"
        cv2.imwrite(test_filename, frame)
        print(f"✅ Success: Frame captured and saved locally as '{test_filename}'.")
    else:
        print("❌ ERROR: Failed to grab video frame from sensor.")

    cap.release()
    print("=" * 60)
    print("Optical diagnostic completed.")
    print("=" * 60)

if __name__ == "__main__":
    run_camera_test()