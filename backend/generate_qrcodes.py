import os
import qrcode
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')  # Replace with your project name
django.setup()

from core.models import ControlledDevice  # Replace with your app name

# Create output folder
output_dir = "qr_codes"
os.makedirs(output_dir, exist_ok=True)

# Fetch all devices
devices = ControlledDevice.objects.all()

# Generate QR for each device
for device in devices:
    device_id = device.device_id
    img = qrcode.make(device_id)
    filename = f"{output_dir}/{device_id}.png"
    with open(filename, 'wb') as f:
        img.save(f)
    print(f"✅ Saved QR for {device.name} -> {filename}")
