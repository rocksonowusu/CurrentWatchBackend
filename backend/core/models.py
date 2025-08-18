from ipaddress import ip_address
from pyexpat import model
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

class Controller(models.Model):
    controller_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=100, default="ESP32 Controller")
    owner = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='controllers', null=True, blank=True)
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='controllers')
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.controller_id} - {self.name}"
        

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
    name = models.CharField(max_length=100, default="New Device", help_text="User-friendly display name")
    type = models.CharField(max_length=10, choices=DEVICE_TYPES, default='socket')
    owner = models.ForeignKey(UserProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='devices')
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices')
    controller = models.ForeignKey(Controller, on_delete=models.CASCADE, null=True, blank=True, related_name='devices')
    hardware_pin = models.CharField(
        max_length=10, 
        null=True, 
        blank=True, 
        help_text="Hardware pin name that ESP32 uses (kitchen, living, light1, etc.) - DO NOT change this after pairing"
    )
    is_paired = models.BooleanField(default=False)
    pairing_code = models.CharField(max_length=10, unique=True)
    endpoint_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=3, choices=STATUS_CHOICES, default='off')
    current_value = models.FloatField(null=True, blank=True, help_text="Current in Amps (only for sockets)")

    def __str__(self):
        return f"{self.name} ({self.device_id}) - Pin: {self.hardware_pin}"

    def save(self, *args, **kwargs):
        # Only set hardware_pin from device_id if it's not already set
        if not self.hardware_pin and self.device_id:
            parts = self.device_id.split('-')
            if len(parts) >= 2:
                self.hardware_pin = parts[-1]
        
        # Generate pairing code if not exists
        if not self.pairing_code:
            self.generate_pairing_code()
        
        # Call super().save() only once
        super().save(*args, **kwargs)
    
    def generate_pairing_code(self):
        """Generate a new unique pairing code"""
        while True:
            code = get_random_string(6, '0123456789')
            if not Device.objects.filter(pairing_code=code).exists():
                self.pairing_code = code
                break
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
        return buffer
    
    def pair_device(self, user, room=None):
        """Pair device to user and room"""
        if not self.pairing_code:
            return False
            
        self.is_paired = True
        self.owner = user
        self.room = room
        self.last_seen = timezone.now()
        self.save()
        return True

    @property
    def display_info(self):
        """Return display information for admin/debugging"""
        return {
            'user_name': self.name,
            'hardware_pin': self.hardware_pin,
            'device_id': self.device_id
        }

    class Meta:
        ordering = ['-created_at']
        # Add unique constraint for controller + hardware_pin
        unique_together = ['controller', 'hardware_pin']

# Device commands queue
class DeviceCommand(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='commands', null=True, blank=True)
    controller = models.ForeignKey(Controller, on_delete=models.CASCADE, related_name='commands')
    action = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    is_executed = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('executing', 'Executing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending'
    )
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)

    def mark_as_executing(self):
        self.status = 'executing'
        self.save()

    def mark_as_completed(self):
        self.status = 'completed'
        self.is_executed = True
        self.executed_at = timezone.now()
        self.save()

    def mark_as_failed(self):
        self.status = 'failed'
        self.retry_count += 1
        self.save()

    def __str__(self):
        device_info = f"{self.device.name} ({self.device.hardware_pin})" if self.device else "System Command"
        return f"{self.action} -> {device_info}"

    class Meta:
        ordering = ['-created_at']


class DeviceAlert(models.Model):
    ALERT_TYPES = (
        ('overload', 'Overload'),
        ('short_circuit', 'Short Circuit'),
        ('offline', 'Device Offline'),
        ('high_current', 'High Current'),
    )
    
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='alerts')
    controller = models.ForeignKey(Controller, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.alert_type} - {self.device.name if self.device else 'Unknown Device'}"
    
    class Meta:
        ordering = ['-created_at']


class ActivityLog(models.Model):
    LOG_TYPES = (
        ('error', 'Error'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    )
    
    ACTION_TYPES = (
        ('device_control', 'Device Control'),
        ('device_pairing', 'Device Pairing'),
        ('device_unpaired', 'Device Unpaired'),
        ('system_alert', 'System Alert'),
        ('user_action', 'User Action'),
        ('controller_status', 'Controller Status'),
        ('overload_detected', 'Overload Detected'),
        ('short_circuit', 'Short Circuit'),
        ('lockout_activated', 'Lockout Activated'),
        ('lockout_cleared', 'Lockout Cleared'),
    )

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='activity_logs', null=True, blank=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='activity_logs', null=True, blank=True)
    controller = models.ForeignKey(Controller, on_delete=models.CASCADE, related_name='activity_logs', null=True, blank=True)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='activity_logs', null=True, blank=True)
    
    log_type = models.CharField(max_length=10, choices=LOG_TYPES, default='info')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES, default='user_action')
    message = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    
    # Additional context fields
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=50, default='web', help_text="web, mobile, sms, esp32, system")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['log_type', 'created_at']),
            models.Index(fields=['action_type', 'created_at']),
            models.Index(fields=['device', 'created_at']),
        ]

    def __str__(self):
        user_info = f"{self.user.email}" if self.user else "System"
        device_info = f" - {self.device.name}" if self.device else ""
        return f"[{self.log_type.upper()}] {user_info}{device_info}: {self.message}"

    @classmethod
    def log_device_control(cls, user, device, action, source='web', success=True, details='', ip_address=None):
        """Log device control actions"""
        log_type = 'info' if success else 'error'
        status = 'successful' if success else 'failed'
        message = f"Device {action} {status}"
        
        return cls.objects.create(
            user=user,
            device=device,
            controller=device.controller if device else None,
            room=device.room if device else None,
            log_type=log_type,
            action_type='device_control',
            message=message,
            details=details,
            source=source,
            ip_address=ip_address
        )

    @classmethod
    def log_device_pairing(cls, user, device, success=True, details='', source='web', ip_address=None):
        """Log device pairing actions"""
        log_type = 'info' if success else 'error'
        status = 'paired successfully' if success else 'pairing failed'
        message = f"Device {status}"
        
        return cls.objects.create(
            user=user,
            device=device,
            controller=device.controller if device else None,
            room=device.room if device else None,
            log_type=log_type,
            action_type='device_pairing',
            message=message,
            details=details,
            source=source,
            ip_address=ip_address
        )

    @classmethod
    def log_system_alert(cls, device, alert_type, message, details='', controller=None):
        """Log system alerts (overload, short circuit, etc.)"""
        log_type_mapping = {
            'overload': 'warning',
            'short_circuit': 'error',
            'lockout_activated': 'warning',
            'lockout_cleared': 'info',
            'device_offline': 'warning',
        }
        
        log_type = log_type_mapping.get(alert_type, 'warning')
        
        return cls.objects.create(
            user=device.owner if device else None,
            device=device,
            controller=controller or (device.controller if device else None),
            room=device.room if device else None,
            log_type=log_type,
            action_type=alert_type,
            message=message,
            details=details,
            source='esp32'
        )

    @classmethod
    def log_user_action(cls, user, message, details='', source='web', ip_address=None, user_agent=''):
        """Log general user actions"""
        return cls.objects.create(
            user=user,
            log_type='info',
            action_type='user_action',
            message=message,
            details=details,
            source=source,
            ip_address=ip_address,
            user_agent=user_agent
        )

