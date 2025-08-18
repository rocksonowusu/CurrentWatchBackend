def create_activity_logs_from_existing_data():
    """
    One-time function to create activity logs from existing DeviceCommand and DeviceAlert data
    Run this in Django shell after adding the ActivityLog model
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import DeviceCommand, DeviceAlert, ActivityLog  # adjust 'core' to your app name

    print("Creating activity logs from existing device commands...")

    # Create logs from DeviceCommands
    commands = DeviceCommand.objects.all().order_by('created_at')
    for cmd in commands:
        if cmd.device and cmd.device.owner:
            # Always store device control logs as 'info'
            log_type = 'info'
            message = f"Device turned {cmd.action}"
            details = f"Command executed via {cmd.controller.name if cmd.controller else 'unknown controller'}"

            ActivityLog.objects.create(
                user=cmd.device.owner,
                device=cmd.device,
                controller=cmd.controller,
                room=cmd.device.room,
                log_type=log_type,
                action_type='device_control',
                message=message,
                details=details,
                source='system',
                created_at=cmd.executed_at or cmd.created_at
            )

    

    # Create logs from DeviceAlerts
    alerts = DeviceAlert.objects.all().order_by('created_at')
    for alert in alerts:
        if alert.device and alert.device.owner:
            # Map alert type to log_type
            log_type_mapping = {
                'overload': 'warning',
                'short_circuit': 'error',
                'offline': 'warning',
                'high_current': 'warning',
            }
            log_type = log_type_mapping.get(alert.alert_type, 'warning')

            ActivityLog.objects.create(
                user=alert.device.owner,
                device=alert.device,
                controller=alert.controller,
                room=alert.device.room,
                log_type=log_type,
                action_type='system_alert',
                message=alert.message,
                details=f"Alert type: {alert.get_alert_type_display()}",
                source='system',
                created_at=alert.created_at
            )
    print("Creating activity logs from existing device alerts...")
    print("Done creating activity logs.")
