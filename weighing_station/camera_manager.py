import cv2
import time
import threading

class CameraManager:
    """
    Manages QR code scanning via webcam.
    Runs in a separate thread to avoid blocking the GUI.
    """
    def __init__(self, callback_on_qr_found=None, camera_index=1):
        self.camera_index = camera_index
        self.callback = callback_on_qr_found
        self.running = False
        self.thread = None
        self.cap = None
        self.detector = cv2.QRCodeDetector() # Initialize OpenCV detector

    def start_camera(self):
        """Starts the camera thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop_camera(self):
        """Stops the camera and closes the window."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        
        # Ensure everything is closed
        if self.cap and self.cap.isOpened():
            self.cap.release()
        cv2.destroyAllWindows()

    def _capture_loop(self):
        """
        Main camera capture loop (runs in background).
        """
        try:
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            
            # If index 1 fails, try index 0
            if not self.cap.isOpened():
                print(f"[Camera] Index {self.camera_index} failed. Trying Index 0...")
                self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

            if not self.cap.isOpened():
                print("[Camera] Error: No camera found!")
                self.running = False
                return

            # Set resolution (consistent with original script)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            last_data = None
            last_time = 0
            cooldown = 2.0 # Wait seconds before next scan

            print("[Camera] Started. 'QR Scanner' window should appear.")

            while self.running:
                ret, frame = self.cap.read()
                if not ret:
                    break

                # QR Code Detection using OpenCV
                data, bbox, _ = self.detector.detectAndDecode(frame)
                
                if bbox is not None and data:
                    # Draw rectangle (bbox is a numpy array of points)
                    points = bbox[0].astype(int)
                    n = len(points)
                    for i in range(n):
                        cv2.line(frame, tuple(points[i]), tuple(points[(i+1) % n]), (0, 255, 0), 3)

                    # Check cooldown to prevent multiple sends
                    now = time.time()
                    if (now - last_time) > cooldown:
                        print(f"[Camera] QR detected: {data}")
                        last_data = data
                        last_time = now
                        
                        # Send callback to GUI (if exists)
                        if self.callback:
                            self.callback(data)

                # Show Window
                cv2.imshow("QR Scanner (Press 'q' to quit)", frame)

                # 'q' key exits this loop
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    self.stop_camera()
                    break
            
        except Exception as e:
            print(f"[Camera] Error in Capture-Loop: {e}")
        finally:
            if self.cap: self.cap.release()
            cv2.destroyAllWindows()
            self.running = False
