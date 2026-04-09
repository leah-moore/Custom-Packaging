"""Lists all available cameras on Windows and saves a preview from each."""
 
import cv2
 
print("Scanning for cameras...")
for i in range(6):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)  # CAP_DSHOW = Windows DirectShow
    if cap.isOpened():
        ret, frame = cap.read()
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        status = "OK" if ret else "opened but no frame"
        print(f"  Device {i}: {w}x{h}  [{status}]")
        if ret:
            cv2.imwrite(f"camera_{i}.png", frame)
            print(f"             → saved camera_{i}.png")
        cap.release()
    else:
        print(f"  Device {i}: not available")