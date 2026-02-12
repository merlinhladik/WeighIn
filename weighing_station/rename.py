import base64
import json
from urllib.parse import urlparse, parse_qs

def decode_base64_url(data: str) -> bytes:
    """Decodes base64url string with auto-padding."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def extract_jwt_from_input(raw_input: str) -> str:
    """
    Extracts a JWT token from various input formats:
    - Raw JWT: header.payload.signature
    - Full URL: https://... ? ... &s=<JWT>
    - Parameter string: "s=<JWT>"
    Cleans up whitespace and newlines.
    """
    cleaned_input = raw_input.strip().replace("\n", "").replace("\r", "").replace(" ", "")

    # Extract token from 's=' parameter prefix
    if cleaned_input.startswith("s="):
        return cleaned_input[2:]

    # Parse JWT from 's' query parameter in URLs
    if cleaned_input.startswith("http://") or cleaned_input.startswith("https://"):
        parsed_url = urlparse(cleaned_input)
        query_params = parse_qs(parsed_url.query)
        token = query_params.get("s", [None])[0]
        if token:
            return token
        
        # Check URL fragment for #s=TOKEN
        if parsed_url.fragment and parsed_url.fragment.startswith("s="):
            return parsed_url.fragment[2:]
            
        raise ValueError("JWT token not found in URL 's' parameter.")

    # Assume direct JWT input
    return cleaned_input

def decode_jwt_without_verification(token: str) -> dict:
    """Decodes JWT header and payload (data extraction only, no signature check)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid JWT: Need Header.Payload.Signature format. Received {len(parts)} parts.")

    header = json.loads(decode_base64_url(parts[0]).decode("utf-8"))
    payload = json.loads(decode_base64_url(parts[1]).decode("utf-8"))

    return {"header": header, "payload": payload}

if __name__ == "__main__":
    raw_user_input = input("-> Paste the QR content here (URL or raw JWT):\n").strip()

    try:
        jwt_token = extract_jwt_from_input(raw_user_input)
        decoded_data = decode_jwt_without_verification(jwt_token)

        print("\n--- TOKEN HEADER ---")
        print(json.dumps(decoded_data["header"], indent=2, ensure_ascii=False))

        print("\n--- TOKEN PAYLOAD ---")
        print(json.dumps(decoded_data["payload"], indent=2, ensure_ascii=False))

        payload = decoded_data["payload"]
        print("\n--- EXTRACTED FIGHTER DATA ---")
        print(f"First Name:    {payload.get('FN')}")
        print(f"Last Name:     {payload.get('LN')}")
        print(f"Date of Birth: {payload.get('DOB')}")
        print(f"Judopass NO:   {payload.get('NO')}")
        print(f"Internal ID:   {payload.get('ID')}")
        
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
