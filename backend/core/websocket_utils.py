# core/websocket_utils.py
import re
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone

from core.models import UserProfile

logger = logging.getLogger(__name__)

def sanitize_group_name(name):
    """Sanitize group name to only contain allowed characters"""
    return re.sub(r'[^a-zA-Z0-9_\.-]', '_', name)

def _safe_send(user_id, message):
    """Helper function to safely send WebSocket messages with error handling"""
    try:
        channel_layer = get_channel_layer()
        # Create group name using user ID
        group_name = f'user_{user_id}'
        group_name = sanitize_group_name(group_name)
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            message
        )
        return True
    except Exception as e:
        logger.error(f"WebSocket send error: {str(e)}. Group: {group_name}", exc_info=True)
        return False

def send_device_status_update(user_email, device_id, status, current_value=None):
    """Send device status update via Websocket"""
    try:
        user = UserProfile.objects.filter(email=user_email).first()
        if not user:
            logger.error(f"Failed to send device status: no user found with email {user_email}")
            return False
            
        message = {
            'type': 'device_status',
            'timestamp': timezone.now().isoformat(),
            'data': {
                'device_id': device_id,
                'status': status,
                'current_value': current_value,
                'last_seen': timezone.now().isoformat()
            }
        }

        print(f"📤 WebSocket message being sent: {message}")
        
        return _safe_send(user.id, message)
        
    except Exception as e:
        logger.error(f"Critical error in send_device_status_update: {str(e)}", exc_info=True)
        return False

def send_command_status_update(user_email, command_id, device_id, status, time_remaining=None, error=None):
    """Send command status update via WebSocket"""
    try:
        user = UserProfile.objects.filter(email=user_email).first()
        if not user:
            logger.error("Failed to send command update: invalid user")
            return False
            
        message = {
            'type': 'command_update',
            'timestamp': timezone.now().isoformat(),
            'data': {
                'command_id': command_id,
                'device_id': device_id,
                'status': status,
                'time_remaining': time_remaining,
                'error': error
            }
        }
        
        return _safe_send(user.id, message)
        
    except Exception as e:
        logger.error(f"Critical error in send_command_status_update: {str(e)}", exc_info=True)
        return False

def send_alert_notification(user_email, alert_type, title, message, device_id=None):
    """Send alert notification via WebSocket"""
    try:
        user = UserProfile.objects.filter(email=user_email).first()
        if not user:
            logger.error(f"Failed to send alert: no user found with email {user_email}")
            return False
            
        message_data = {
            'type': 'alert_notification',
            'timestamp': timezone.now().isoformat(),
            'data': {
                'alert_type': alert_type,  # 'short_circuit', 'overload', 'device_off', 'success', etc.
                'title': title,
                'message': message,
                'device_id': device_id
            }
        }

        print(f"🚨 Alert WebSocket message being sent: {message_data}")
        
        return _safe_send(user.id, message_data)
        
    except Exception as e:
        logger.error(f"Critical error in send_alert_notification: {str(e)}", exc_info=True)
        return False