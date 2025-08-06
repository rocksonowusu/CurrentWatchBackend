from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
import qrcode
from django.core.files import File
from io import BytesIO

class UserProfile(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True)    
    phone_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email

class Room(models.Model):
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=100, default="home")
    owner = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='rooms')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.owner.email}"

    class Meta:
        unique_together = ['name', 'owner']  # Prevent duplicate room names per user

DEVICE_TYPES = (
    ('socket', 'Socket'),
    ('light', 'Light'),
    ('fan', 'Fan'),
)

STATUS_CHOICES = (
    ('on', 'On'),
    ('off', 'Off'),
)

class Device(models.Model):
    device_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=100, default="New Device")
    type = models.CharField(max_length=10, choices=DEVICE_TYPES, default='socket')
    owner = models.ForeignKey(UserProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='devices')
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices')
    is_paired = models.BooleanField(default=False)
    pairing_code = models.CharField(max_length=10, unique=True)
    endpoint_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=3, choices=STATUS_CHOICES, default='off')
    current_value = models.FloatField(null=True, blank=True, help_text="Current in Amps (only for sockets)")


    def __str__(self):
        return f"{self.name} ({self.device_id})"
    
    def generate_pairing_code(self):
        self.pairing_code = get_random_string(6, '0123456789')
        self.save()
        return self.pairing_code
    
    def generate_qr_code(self):
        # Create QR data string
        qr_data = f"device_id:{self.device_id}|pairing_code:{self.pairing_code}"
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        
        # Save to file (if you have a file field)
        # self.qr_code.save(
        #     f'qr_{self.device_id}.png',
        #     File(buffer),
        #     save=False
        # )
        # self.save()
        return buffer
    
    def pair_device(self, user, room=None):
        if not self.pairing_code:
            return False
            
        self.is_paired = True
        self.owner = user
        self.room = room
        self.last_seen = timezone.now()
        self.save()
        return True

    class Meta:
        ordering = ['-created_at']