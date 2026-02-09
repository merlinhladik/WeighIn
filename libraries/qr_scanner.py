import cv2
import json
import sys
import os

# usage: python qr_reader_with_image.py "path/to/image.png"

def scan_qr_from_image(image_path):
    print(f"[INFO] Loading image: {image_path} ...")

    # Verify file existence
    if not os.path.exists(image_path):
        print(f"[ERROR] File not found: {image_path}")
        return

    # Load image using OpenCV
    img = cv2.imread(image_path)
    if img is None:
        print("[ERROR] Could not load image (Check path and format)")
        return

    # Initialize detector and decode QR code
    detector = cv2.QRCodeDetector()
    data, bbox, straight_qrcode = detector.detectAndDecode(img)

    if data:
        print(f"[SUCCESS] QR CODE FOUND!")
        print(f"   Content (Raw): {data}\n")
        
        # Parse JSON athlete metadata
        try:
            parsed_data = json.loads(data)
            print("   [INFO] Metadata found:")
            print(f"   Name:   {parsed_data.get('name')}")
            print(f"   ID:     {parsed_data.get('id')}")
            print(f"   Club:   {parsed_data.get('club')}")
        except json.JSONDecodeError:
            print("   [WARN] QR content is not JSON format.")
    else:
        print("[WARN] NO QR Code detected in this image.")
        print("   Tip: Is the image sharp enough? Is the QR code fully visible?")

if __name__ == "__main__":
    # Check if a path was passed, otherwise use default
    target_file = "judo_pass_example.png" # Fallback
    
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    
    scan_qr_from_image(target_file)
