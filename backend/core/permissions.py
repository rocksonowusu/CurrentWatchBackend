from rest_framework import permissions
import logging
from .models import Device

logger = logging.getLogger(__name__)

class DeviceOwnerPermission(permissions.BasePermission):
    """Check if device belongs to user's system"""
    def has_permission(self, request, view):
        device_id = request.data.get('device_id')
        email = request.data.get('email')
        
        if not device_id or not email:
            return False
        
        try:
            # Check if device belongs to user's system
            return Device.objects.filter(
                device_id=device_id,
                system__owner__email=email
            ).exists()
        except Exception as e:
            logger.error(f"Permission check error: {str(e)}")
            return False