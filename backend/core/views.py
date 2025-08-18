from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import UserProfile, Room,ActivityLog, Device, Controller, DeviceCommand, DeviceAlert
from .serializers import (
    UserProfileSerializer,
    RoomSerializer,
    DeviceSerializer,
    DevicePairingSerializer
)
import secrets
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.db import models
from datetime import timedelta
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .websocket_utils import send_command_status_update, send_device_status_update, send_alert_notification
from django.core.paginator import Paginator
from datetime import timedelta

logger = logging.getLogger(__name__)

class OnboardingStartView(APIView):
    def post(self, request, format=None):
        try:
            data = request.data
            email = data.get('email')
            full_name = data.get('full_name')
            
            if not email or not full_name:
                return Response(
                    {'error': 'Email and full name are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            user_profile, created = UserProfile.objects.update_or_create(
                email=email,
                defaults={'full_name': full_name}
            )
            
            return Response({
                'message': 'Profile updated successfully',
                'email': user_profile.email,
                'full_name': user_profile.full_name
            }, status=status.HTTP_200_OK)
                
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class PhoneVerificationView(APIView):
    def post(self, request, format=None):
        try:
            data = request.data
            email = data.get('email')
            phone_number = data.get('phone_number')
            
            if not email or not phone_number:
                return Response(
                    {'error': 'Email and phone number are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user_profile = UserProfile.objects.get(email=email)
                user_profile.phone_number = phone_number
                user_profile.phone_verified = True  # Mark as verified
                user_profile.save()
                
                # FIXED: Look for controllers owned by user OR unassigned online controllers
                controllers = Controller.objects.filter(
                    models.Q(owner=user_profile, is_online=True) |
                    models.Q(owner__isnull=True, is_online=True)
                ).distinct()

                if controllers.exists():
                    # Auto-assign unassigned controllers to this user
                    for controller in controllers:
                        if not controller.owner:
                            controller.owner = user_profile
                            controller.save()
                            print(f"📱 Assigned controller {controller.controller_id} to user {user_profile.email}")
                    
                    # Create a special "test_alert" command for each controller
                    for controller in controllers:
                        #Create a dummy device for system commands
                        # Create a dummy device for system commands with unique check
                        system_device_id = f"{controller.controller_id}-system"
                        try:
                            dummy_device = Device.objects.get(device_id=system_device_id)
                            # Update existing device
                            dummy_device.controller = controller
                            dummy_device.is_paired = True
                            dummy_device.hardware_pin = 'system'
                            dummy_device.save()
                        except Device.DoesNotExist:
                            # Create new device
                            dummy_device = Device.objects.create(
                                device_id=system_device_id,
                                name='System Device',
                                type='socket',
                                controller=controller,
                                pairing_code=get_random_string(6, '0123456789'),
                                is_paired=True,
                                hardware_pin='system'
                            )

                        DeviceCommand.objects.create(
                            device=dummy_device,
                            controller=controller,
                            action=f'test_alert:{phone_number}'
                        )

                    return Response({
                        'message': 'Phone number saved and test alert sent to the controllers',
                        'phone_number': phone_number,
                        'controllers_notified': controllers.count()
                    }, status=status.HTTP_200_OK)
                else:
                    return Response(
                        {'error': 'No online controllers found - please ensure your device is connected'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found - complete onboarding first'},
                    status=status.HTTP_404_NOT_FOUND
                )
                    
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class RoomCreationView(APIView):
    def post(self, request, format=None):
        try:
            data = request.data
            email = data.get('email')
            room_name = data.get('name')
            icon = data.get('icon', 'home')
            
            if not email or not room_name:
                return Response(
                    {'error': 'Email and room name are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                
                # Create the room directly associated with the user
                room = Room.objects.create(
                    name=room_name,
                    icon=icon,
                    owner=user
                )
                
                return Response({
                    'message': 'Room created successfully',
                    'room_id': room.id,
                    'room_name': room.name
                }, status=status.HTTP_201_CREATED)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found - complete onboarding first'},
                    status=status.HTTP_404_NOT_FOUND
                )
                    
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ControllerRegistrationView(APIView):
    def post(self, request, format=None):
        """ESP32 registers itself with the backend"""
        try:
            controller_id = request.data.get('controller_id')
            device_types = request.data.get('device_types', [])
            
            if not controller_id:
                return Response(
                    {'error': 'Controller ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get or create controller
            controller, created = Controller.objects.get_or_create(
                controller_id=controller_id,
                defaults={
                    'name': f'Controller {controller_id[-4:]}',
                    'is_online': True,
                    'last_seen': timezone.now()
                }
            )
            
            if not created:
                controller.is_online = True
                controller.last_seen = timezone.now()
                controller.save()
            
            # Create or update devices for this controller
            device_mapping = {
                'kitchen': 'socket',
                'living': 'socket', 
                'light1': 'light',
                'light2': 'light',
                'fan': 'fan'
            }
            
            for device_name in device_types:
                device_type = device_mapping.get(device_name, 'socket')
                device_id = f"{controller_id}-{device_name}"
                
                device, device_created = Device.objects.get_or_create(
                    device_id=device_id,
                    defaults={
                        'name': f'{device_name.title()} Device',
                        'type': device_type,
                        'controller': controller,
                        'hardware_pin': device_name,
                        'pairing_code': get_random_string(6, '0123456789'),
                        'last_seen': timezone.now()
                    }
                )
                
                if not device_created:

                    device.controller = controller
                    device.hardware_pin = device_name
                    device.last_seen = timezone.now()
                    # FIXED: Don't reset controller if device is already paired to a user
                    if not device.is_paired:
                        device.type = device_type
                        device.name = f'{device_name.title()} Device'  
                    device.save()
            
            return Response({
                'message': 'Controller registered successfully',
                'controller_id': controller.controller_id,
                'devices_created': len(device_types)
            }, status=status.HTTP_200_OK)
                    
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DevicePairingInitView(APIView):
    def post(self, request, format=None):
        """Endpoint for ESP32 to initialize pairing"""
        try:
            device_id = request.data.get('device_id')
            device_type = request.data.get('type', 'socket')
            
            if not device_id:
                return Response(
                    {'error': 'Device ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            device, created = Device.objects.get_or_create(
                device_id=device_id,
                defaults={
                    'pairing_code': get_random_string(6, '0123456789'),
                    'name': f"Device {device_id[-4:]}",
                    'type': device_type
                }
            )
            
            if not created:
                device.generate_pairing_code()
                
            return Response({
                'device_id': device.device_id,
                'pairing_code': device.pairing_code,
                'message': 'Device ready for pairing'
            }, status=status.HTTP_200_OK)
                    
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DevicePairingCompleteView(APIView):
    def post(self, request, format=None):
        """Complete device pairing from mobile app"""
        try:
            data = request.data
            email = data.get('email')
            device_id = data.get('device_id')
            pairing_code = data.get('pairing_code')
            room_id = data.get('room_id')
            endpoint_url = data.get('endpoint_url')
            device_name = data.get('device_name')
            device_type = data.get('device_type')
            
            if not email or not device_id or not pairing_code:
                return Response(
                    {'error': 'Email, device ID and pairing code are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get client IP address
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0]
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            
            try:
                user = UserProfile.objects.get(email=email)
                device = Device.objects.get(device_id=device_id, pairing_code=pairing_code)
                
                # FIXED: Store original controller before making changes
                original_controller = device.controller

                # Update device details
                device.is_paired = True
                device.owner = user
                device.endpoint_url = endpoint_url or ''
                device.last_seen = timezone.now()
                
                # FIXED: Update display name but preserve hardware_pin for ESP32 communication
                if device_name:
                    device.name = device_name  # This is the user-friendly display name
                    # hardware_pin remains unchanged - this is what ESP32 uses
                
                if device_type:
                    device.type = device_type
                
                # FIXED: Handle room assignment properly
                if room_id:
                    try:
                        room = Room.objects.get(id=room_id, owner=user)
                        device.room = room
                        print(f"✅ Assigned device {device.device_id} to room {room.name}")
                        
                        # FIXED: Keep the original controller assignment
                        if original_controller and not original_controller.owner:
                            original_controller.owner = user
                            original_controller.room = room
                            original_controller.save()
                            print(f"✅ Assigned controller {original_controller.controller_id} to room {room.name}")
                    except Room.DoesNotExist:
                        print(f"❌ Room {room_id} not found for user {user.email}")
                        pass
                
                device.save()

                # Log the successful pairing
                ActivityLog.log_device_pairing(
                    user=user,
                    device=device,
                    success=True,
                    details=f'Device paired successfully to room: {device.room.name if device.room else "No room"}',
                    source='mobile',
                    ip_address=ip_address
                )
                
                return Response({
                    'message': 'Device paired successfully',
                    'device_id': device.device_id,
                    'device_name': device.name,
                    'hardware_pin': device.hardware_pin,  # Include hardware_pin in response
                    'room_id': device.room.id if device.room else None,
                    'controller_id': device.controller.controller_id if device.controller else None
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found - complete onboarding first'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Device.DoesNotExist:

                # Log the failed pairing attempt
                try:
                    user = UserProfile.objects.get(email=email)
                    ActivityLog.log_user_action(
                        user=user,
                        message='Device pairing failed',
                        details=f'Invalid device ID ({device_id}) or pairing code',
                        source='mobile',
                        ip_address=ip_address
                    )
                except:
                    pass

                return Response(
                    {'error': 'Invalid device ID or pairing code'},
                    status=status.HTTP_404_NOT_FOUND
                )
                    
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeviceCommandsView(APIView):
    def get(self, request, format=None):
        """ESP32 checks for pending commands"""
        try:
            controller_id = request.query_params.get('controller_id')

            if not controller_id:
                return Response(
                    {'error': 'Controller ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                controller = Controller.objects.select_related().get(controller_id=controller_id)

                with transaction.atomic():
                    controller.last_seen = timezone.now()
                    controller.is_online = True
                    controller.save(update_fields=['last_seen', 'is_online'])
                # controller = Controller.objects.get(controller_id=controller_id)
                # controller.last_seen = timezone.now()
                # controller.is_online = True
                # controller.save()

                
                self.cleanup_stale_commands(controller)

                # Get pending commands
                pending_commands = DeviceCommand.objects.filter(
                    controller=controller,
                    is_executed=False,
                    status__in=['pending', 'executing']
                ).order_by('created_at')[:10]

                commands = []


                with transaction.atomic():
                    for cmd in pending_commands:

                        if cmd.status == 'pending':
                            cmd.status = 'executing'
                            cmd.save(update_fields=['status'])

                        if cmd.device:
                            device_hardware_name = cmd.device.hardware_pin
                            if not device_hardware_name:
                                logger.warning(f"Device {cmd.device.device_id} has no hardware pin")
                                device_hardware_name = 'unknown'
                            commands.append({
                                'command_id': cmd.id,
                                'device_name': device_hardware_name,
                                'action': cmd.action,
                                'created_at': cmd.created_at
                            })
                        else:
                            commands.append({
                                'command_id': cmd.id,
                                'device_name': '',
                                'action': cmd.action,
                                'created_at': cmd.created_at
                            })

                return Response({
                    'commands': commands,
                    'timestamp': timezone.now().isoformat()
                }, status=status.HTTP_200_OK)

            except Controller.DoesNotExist:
                return Response(
                    {'error': 'Controller not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

        except Exception as e:
            logger.error(f"Error in DeviceCommandssView: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def cleanup_stale_commands(self, controller):
        """Clean up stale commands more aggressively - 30 seconds"""
        stale_cutoff = timezone.now() - timezone.timedelta(seconds=30)

        with transaction.atomic():
            stale_commands = DeviceCommand.objects.filter(
                controller = controller,
                is_executed = False,
                created_at__lt = stale_cutoff
            )

            stale_count = stale_commands.count()
            if stale_count > 0:
                stale_commands.update(
                    is_executed = True,
                    status = 'failed',
                    executed_at = timezone.now()
                )
                logger.info(f"Cleaned up {stale_count} stale commands for controller {controller.controller_id}")
       

class DeviceControlView(APIView):
    def post(self, request, format=None):
        """Mobile app sends device control commands"""
        try:
            data = request.data
            device_id = data.get('device_id')
            action = data.get('action')

            print(f"🔍 Looking for device with ID: '{device_id}'")

            if not device_id or not action:
                return Response(
                    {'error': 'Device ID and action are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                device = Device.objects.select_related('controller').get(
                    device_id=device_id,
                    is_paired=True
                )

                if not device.controller:
                    return Response(
                        {'error': 'Device not connected to a controller'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Get client IP address
                x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                if x_forwarded_for:
                    ip_address = x_forwarded_for.split(',')[0]
                else:
                    ip_address = request.META.get('REMOTE_ADDR')

                with transaction.atomic():
                    existing_command = DeviceCommand.objects.filter(
                        device=device,
                        is_executed=False,
                        status__in=['pending', 'executing']
                    ).select_for_update().first()

                if existing_command:
                    if timezone.now() - existing_command.created_at > timedelta(seconds=30):
                        existing_command.status = 'failed'
                        existing_command.is_executed = True
                        existing_command.executed_at = timezone.now()
                        existing_command.save()

                        # Log the failed command
                        ActivityLog.log_device_control(
                            user=device.owner,
                            device=device,
                            action=action,
                            source='mobile',
                            success=False,
                            details='Command timeout - previous command was still pending',
                            ip_address=ip_address
                        )
                    else:
                        return Response({
                            'error': 'Command already pending for this device',
                            'command_id': existing_command.id,
                            'status': existing_command.status,
                            'time_remaining': 30 - (timezone.now() - existing_command.created_at).seconds
                        }, status=status.HTTP_409_CONFLICT)


                # Create command for the controller to execute
                command = DeviceCommand.objects.create(
                    device=device,
                    controller=device.controller,
                    action=action.lower(),
                    status='pending'
                )

                #Immediately update device status (for UI responsiveness)
                if action.lower() == 'on':
                    device.status = 'on'
                elif action.lower() == 'off':
                    device.status = 'off'
                device.last_seen = timezone.now()
                device.save(update_fields = ['status', 'last_seen'])

                # Log the device control action
                ActivityLog.log_device_control(
                    user=device.owner,
                    device=device,
                    action=action,
                    source='mobile',
                    success=True,
                    details=f'Command sent to {device.controller.name}',
                    ip_address=ip_address
                )

                # Send WebSocket notification for immediate UI update
                if device.owner:
                    send_device_status_update(
                        user_email=device.owner.email,
                        device_id=device.device_id,
                        status=device.status,
                        current_value=device.current_value
                    )
                    send_command_status_update(
                        user_email=device.owner.email,
                        command_id=command.id,
                        device_id=device.device_id,
                        status='pending'
                    )


                return Response({
                    'message': f'Command sent to {device.name}',
                    'command_id': command.id,
                    'hardware_pin': device.hardware_pin,  # Include for debugging
                    'status': 'pending',
                    'estimated_execution_time': '1-3 seconds'
                }, status=status.HTTP_200_OK)

            except Device.DoesNotExist:
                return Response(
                    {'error': 'Device not found or not paired'},
                    status=status.HTTP_404_NOT_FOUND
                )

        except Exception as e:
            logger.error(f"Error in DeviceControlView: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeviceCommandExecutedView(APIView):
    def post(self, request, format=None):
        """ESP32 reports command execution"""
        try:
            data = request.data
            command_id = data.get('command_id')
            execution_result = data.get('result', 'success')
            
            if not command_id:
                return Response(
                    {'error': 'Command ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                with transaction.atomic():
                    command = DeviceCommand.objects.select_related('device', 'controller').get(id=command_id)
                    command.is_executed = True
                    command.executed_at = timezone.now()
                    command.status = 'completed' if execution_result == 'success' else 'failed'

                    if command.device and execution_result == 'success':
                        if command.action == 'on':
                            command.device.status = 'on'
                        elif command.action == 'off':
                            command.device.status = 'off'
                        command.device.last_seen = timezone.now()
                        command.device.save(update_fields=['status', 'last_seen'])

                        
                    # Send success alert only after ESP32 confirms execution
                    if execution_result == 'success' and command.device and command.device.owner:
                        # Check if we already sent an alert for this device recently (exclude current command)
                        recent_commands = DeviceCommand.objects.filter(
                            device=command.device,
                            action=command.action,
                            status='completed',
                            executed_at__gte=timezone.now() - timedelta(seconds=5)
                        ).exclude(id=command.id).count()
                        
                        if recent_commands == 0:  # No other recent commands
                            send_alert_notification(
                                user_email=command.device.owner.email,
                                alert_type='success',
                                title=f"{command.device.name} {command.action.title()}",
                                message=f"Device turned {command.action} successfully",
                                device_id=command.device.device_id
                            )

                        # Send WebSocket notification for device status update
                        send_device_status_update(
                            user_email=command.device.owner.email,
                            device_id=command.device.device_id,
                            status=command.device.status,
                            current_value=command.device.current_value
                        )
                        send_command_status_update(
                            user_email=command.device.owner.email,
                            command_id=command.id,
                            device_id=command.device.device_id,
                            status=command.status
                        )


                    if command.action.startswith('test_alert:') and command.controller.owner:
                        command.controller.owner.phone_verified = True
                        command.controller.owner.save(update_fields=['phone_verified'])

                return Response({
                    'message': 'Command execution confirmed',
                    'command_id': command_id,
                    'final_status': command.status
                }, status=status.HTTP_200_OK)

            except DeviceCommand.DoesNotExist:
                return Response(
                    {'error': 'Command not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
                
        except Exception as e:
            logger.error(f"Error in DeviceCommandExecutedView: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeviceStatusView(APIView):
    def post(self, request, format=None):
        """Endpoint for ESP32 to report status"""
        try:
            controller_id = request.data.get('controller_id')
            device_status = request.data.get('device_status', {})

            # Add debug logging
            print(f"📊 Received status from {controller_id}: {device_status}")

            if not controller_id:
                return Response(
                    {'error': 'Controller ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                controller = Controller.objects.get(controller_id=controller_id)
                controller.last_seen = timezone.now()
                controller.is_online = True
                controller.save()

                valid_hardware_pins = ['kitchen', 'living', 'light1', 'light2', 'fan']

                # FIXED: Update device statuses using hardware_pin matching
                for hardware_pin, is_on in device_status.items():
                    if hardware_pin not in valid_hardware_pins:
                        continue

                    # Find device by controller and hardware_pin
                    try:
                        device = Device.objects.get(controller=controller, hardware_pin=hardware_pin)
                        old_status = device.status
                        old_current = device.current_value  # Store old current value
                        
                        device.status = 'on' if is_on else 'off'
                        device.last_seen = timezone.now()


                        # Update current values for sockets
                        current_changed = False
                        if hardware_pin == 'kitchen' and 'kitchen_current' in device_status:
                            new_current = device_status['kitchen_current']
                            if device.current_value != new_current:
                                device.current_value = new_current
                                current_changed = True
                        elif hardware_pin == 'living' and 'living_current' in device_status:
                            new_current = device_status['living_current']
                            if device.current_value != new_current:
                                device.current_value = new_current
                                current_changed = True

                        device.save()

                        # Send WebSocket notification if status OR current changed
                        if (old_status != device.status or current_changed) and device.owner:
                            print(f"🔄 Sending WebSocket update for {device.device_id}: status={device.status}, current={device.current_value}")  # Debug log
                            send_device_status_update(
                                user_email=device.owner.email,
                                device_id=device.device_id,
                                status=device.status,
                                current_value=device.current_value
                            )


                    except Device.DoesNotExist:
                        print(f"Device not found for controller {controller_id} and hardware_pin {hardware_pin}")
                        pass

                self.process_device_alerts(controller,device_status)

                return Response({
                    'message': 'Status received'
                }, status=status.HTTP_200_OK)

            except Controller.DoesNotExist:
                return Response(
                    {'error': 'Controller not registered'},
                    status=status.HTTP_404_NOT_FOUND
                )

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def process_device_alerts(self, controller, device_status):
        """Process device alerts and faults from status data"""
        try:
            # Check for fault states and create alerts/logs
            for device_key in ['kitchen', 'living']:
                fault_key = f"{device_key}_fault_detected"
                locked_key = f"{device_key}_locked"
                lockout_type_key = f"{device_key}_lockout_type"
                
                if device_status.get(fault_key, False):
                    try:
                        device = Device.objects.get(controller=controller, hardware_pin=device_key)
                        
                        # Determine alert type from lockout type
                        lockout_type = device_status.get(lockout_type_key, 'unknown')
                        if lockout_type == 'short_circuit':
                            alert_type = 'short_circuit'
                            message = f'Short circuit detected in {device.name}'
                        elif lockout_type == 'overload':
                            alert_type = 'overload'
                            message = f'Overload detected in {device.name}'
                        else:
                            alert_type = 'offline'
                            message = f'Fault detected in {device.name}'

                        # Create alert (avoid duplicates by checking recent alerts)
                        recent_alert = DeviceAlert.objects.filter(
                            device=device,
                            alert_type=alert_type,
                            created_at__gte=timezone.now() - timedelta(minutes=10)
                        ).first()

                        if not recent_alert:
                            DeviceAlert.objects.create(
                                device=device,
                                controller=controller,
                                alert_type=alert_type,
                                message=message
                            )

                            # Create activity log
                            ActivityLog.log_system_alert(
                                device=device,
                                alert_type=alert_type,
                                message=message,
                                details=f'Alert from controller {controller.controller_id}',
                                controller=controller
                            )

                            print(f"🚨 Created alert: {alert_type} for {device.name}")

                    except Device.DoesNotExist:
                        # Device doesn't exist, skip
                        pass

        except Exception as e:
            print(f"❌ Error processing device alerts: {e}")

class DeviceAlertsView(APIView):
    def post(self, request, format=None):
        """ESP32 sends alerts to backend"""
        try:
            controller_id = request.data.get('controller_id')
            device_name = request.data.get('device_name')  # This should be hardware_pin
            alert_type = request.data.get('alert_type')
            message = request.data.get('message')
            
            print(f"🚨 Alert received: controller={controller_id}, device={device_name}, type={alert_type}, message={message}")
            
            if not all([controller_id, device_name, alert_type, message]):
                return Response(
                    {'error': 'All fields (controller_id, device_name, alert_type, message) are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                controller = Controller.objects.get(controller_id=controller_id)
                
                # FIXED: Find device by hardware_pin instead of device_id
                try:
                    device = Device.objects.get(controller=controller, hardware_pin=device_name)
                except Device.DoesNotExist:
                    print(f"❌ Device not found for controller {controller_id} and hardware_pin {device_name}")
                    return Response(
                        {'error': f'Device not found for hardware_pin: {device_name}'},
                        status=status.HTTP_404_NOT_FOUND
                    )
                
                # Check for duplicate alerts within the last minute
                recent_alert = DeviceAlert.objects.filter(
                    device=device,
                    alert_type=alert_type,
                    created_at__gte=timezone.now() - timedelta(minutes=10)
                ).first()
                
                if recent_alert:
                    print(f"⚠️ Duplicate alert ignored: {alert_type} for {device.name}")
                    return Response({
                        'message': 'Duplicate alert ignored',
                        'alert_id': recent_alert.id
                    }, status=status.HTTP_200_OK)
                
                # Create new alert
                alert = DeviceAlert.objects.create(
                    device=device,
                    controller=controller,
                    alert_type=alert_type,
                    message=message
                )

                if device.owner:
                    send_alert_notification(
                        user_email=device.owner.email,
                        alert_type=alert_type,
                        title=f"{device.name} Alert", 
                        message=message,
                        device_id=device.device_id
                    )

                # Create activity log for the alert
                ActivityLog.log_system_alert(
                    device=device,
                    alert_type=alert_type,
                    message=message,
                    details=f'Alert from controller {controller.controller_id}',
                    controller=controller
                )
                
                print(f"✅ Alert created: {alert_type} for {device.name}")
                
                # TODO: Send push notification to device owner
                # TODO: Send SMS alert if configured
                
                return Response({
                    'message': 'Alert received and processed',
                    'alert_id': alert.id
                }, status=status.HTTP_200_OK)
                
            except Controller.DoesNotExist:
                return Response(
                    {'error': f'Controller not found: {controller_id}'},
                    status=status.HTTP_404_NOT_FOUND
                )
                    
        except Exception as e:
            print(f"❌ Error in DeviceAlertsView: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
class DeviceListView(APIView):
    def get(self, request, format=None):
        """Get all paired devices for a user"""
        try:
            email = request.query_params.get('email')
            
            if not email:
                return Response(
                    {'error': 'Email is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                devices = Device.objects.filter(owner=user, is_paired=True)
                
                device_list = []
                for device in devices:
                    device_list.append({
                        'device_id': device.device_id,
                        'name': device.name,  # User-friendly name
                        'hardware_pin': device.hardware_pin,  # ESP32 hardware reference
                        'type': device.type,
                        'status': device.status,
                        'room_id': device.room.id if device.room else None,
                        'room_name': device.room.name if device.room else None,
                        'controller_id': device.controller.controller_id if device.controller else None,
                        'is_paired': device.is_paired,
                        'last_seen': device.last_seen,
                        'created_at': device.created_at,
                        'current_value': device.current_value
                    })
                
                return Response({
                    'devices': device_list
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                    
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeviceCommandStatusView(APIView):
    def get(self, request, command_id, format=None):
        try:
            command = DeviceCommand.objects.get(id=command_id)
            return Response({
                'command_id': command.id,
                'status': command.status,
                'created_at': command.created_at,
                'executed_at': command.executed_at
            }, status=status.HTTP_200_OK)
        except DeviceCommand.DoesNotExist:
            return Response(
                {'error': 'Command not found'},
                status=status.HTTP_404_NOT_FOUND
            )

class ActivityLogListView(APIView):
    """Get activity logs for a user with filtering and pagination"""
    
    def get(self, request, format=None):
        try:
            email = request.query_params.get('email')
            if not email:
                return Response(
                    {'error': 'Email is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                
                # Get query parameters for filtering
                log_type = request.query_params.get('type', 'all')  # all, error, warning, info
                search_query = request.query_params.get('search', '')
                date_filter = request.query_params.get('date', 'all')  # all, today, yesterday, week
                device_id = request.query_params.get('device_id', '')
                page = int(request.query_params.get('page', 1))
                page_size = int(request.query_params.get('page_size', 5))
                
                # Base queryset - get logs for the user
                queryset = ActivityLog.objects.filter(user=user).select_related(
                    'device', 'controller', 'room'
                )
                
                # Apply filters
                if log_type != 'all':
                    queryset = queryset.filter(log_type=log_type)
                
                if search_query:
                    queryset = queryset.filter(
                        models.Q(message__icontains=search_query) |
                        models.Q(details__icontains=search_query) |
                        models.Q(device__name__icontains=search_query) |
                        models.Q(room__name__icontains=search_query)
                    )
                
                if device_id:
                    queryset = queryset.filter(device__device_id=device_id)
                
                # Date filtering
                if date_filter != 'all':
                    now = timezone.now()
                    if date_filter == 'today':
                        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        queryset = queryset.filter(created_at__gte=start_date)
                    elif date_filter == 'yesterday':
                        yesterday = now - timedelta(days=1)
                        start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                        end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
                        queryset = queryset.filter(created_at__range=[start_date, end_date])
                    elif date_filter == 'week':
                        week_ago = now - timedelta(days=7)
                        queryset = queryset.filter(created_at__gte=week_ago)
                
                # Paginate results
                paginator = Paginator(queryset, page_size)
                page_obj = paginator.get_page(page)
                
                # Serialize logs
                logs = []
                for log in page_obj:
                    logs.append({
                        'id': log.id,
                        'timestamp': log.created_at.isoformat(),
                        'type': log.log_type,
                        'action_type': log.action_type,
                        'message': log.message,
                        'details': log.details,
                        'room': log.room.name if log.room else None,
                        'device': {
                            'id': log.device.device_id,
                            'name': log.device.name,
                            'type': log.device.type
                        } if log.device else None,
                        'controller': {
                            'id': log.controller.controller_id,
                            'name': log.controller.name
                        } if log.controller else None,
                        'source': log.source,
                        'ip_address': log.ip_address
                    })
                
                return Response({
                    'logs': logs,
                    'pagination': {
                        'current_page': page_obj.number,
                        'total_pages': paginator.num_pages,
                        'total_count': paginator.count,
                        'has_next': page_obj.has_next(),
                        'has_previous': page_obj.has_previous()
                    }
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            logger.error(f"Error in ActivityLogListView: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class UserProfileUpdateView(APIView):
    def get(self, request, format=None):
        """Get user profile details"""
        try:
            email = request.query_params.get('email')
            if not email:
                return Response(
                    {'error': 'Email is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                return Response({
                    'email': user.email,
                    'full_name': user.full_name,
                    'phone_number': user.phone_number,
                    'phone_verified': user.phone_verified,
                    'created_at': user.created_at.isoformat()
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def put(self, request, format=None):
        """Update user profile"""
        try:
            email = request.data.get('email')
            phone_number = request.data.get('phone_number')
            full_name = request.data.get('full_name')
            
            if not email:
                return Response(
                    {'error': 'Email is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                
                if phone_number is not None:
                    user.phone_number = phone_number
                if full_name is not None:
                    user.full_name = full_name
                    
                user.save()
                
                # Log the update
                ActivityLog.log_user_action(
                    user=user,
                    message='Profile updated',
                    details=f'Updated profile information',
                    source='mobile',
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
                return Response({
                    'message': 'Profile updated successfully',
                    'email': user.email,
                    'full_name': user.full_name,
                    'phone_number': user.phone_number
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeviceManagementView(APIView):
    def delete(self, request, device_id, format=None):
        """Remove/unpair a device"""
        try:
            email = request.data.get('email')
            if not email:
                return Response(
                    {'error': 'Email is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                device = Device.objects.get(device_id=device_id, owner=user)
                
                device_name = device.name
                
                # Reset device to unpaired state instead of deleting
                device.is_paired = False
                device.owner = None
                device.room = None
                device.generate_pairing_code()  # Generate new pairing code
                device.save()
                
                # Log the device removal
                ActivityLog.log_user_action(
                    user=user,
                    message='Device unpaired',
                    details=f'Device "{device_name}" was unpaired and reset',
                    source='mobile',
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                
                return Response({
                    'message': f'Device "{device_name}" has been unpaired successfully'
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Device.DoesNotExist:
                return Response(
                    {'error': 'Device not found or not owned by user'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SystemSettingsView(APIView):
    def get(self, request, format=None):
        """Get system settings for a user"""
        try:
            email = request.query_params.get('email')
            if not email:
                return Response(
                    {'error': 'Email is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                
                # Get user's devices count and status
                devices = Device.objects.filter(owner=user, is_paired=True)
                controllers = Controller.objects.filter(owner=user)
                
                # Get recent alerts
                recent_alerts = DeviceAlert.objects.filter(
                    device__owner=user,
                    is_resolved=False,
                    created_at__gte=timezone.now() - timedelta(hours=24)
                ).order_by('-created_at')[:1]
                
                active_alert = None
                if recent_alerts.exists():
                    alert = recent_alerts.first()
                    active_alert = {
                        'id': str(alert.id),
                        'message': alert.message,
                        'timestamp': alert.created_at.strftime('%H:%M'),
                        'type': alert.alert_type
                    }
                
                return Response({
                    'devices_count': devices.count(),
                    'online_devices': devices.filter(status='on').count(),
                    'controllers_count': controllers.count(),
                    'online_controllers': controllers.filter(is_online=True).count(),
                    'active_alert': active_alert,
                    'master_toggle': True,  # You can add this to UserProfile model if needed
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class EmergencyControlsView(APIView):
    def post(self, request, format=None):
        """Handle emergency controls"""
        try:
            email = request.data.get('email')
            action = request.data.get('action')  # 'shutdown_all' or 'system_reset'
            
            if not email or not action:
                return Response(
                    {'error': 'Email and action are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                
                if action == 'shutdown_all':
                    # Turn off all user's devices
                    devices = Device.objects.filter(owner=user, is_paired=True)
                    controllers = set()
                    
                    with transaction.atomic():
                        for device in devices:
                            if device.controller:
                                controllers.add(device.controller)
                                DeviceCommand.objects.create(
                                    device=device,
                                    controller=device.controller,
                                    action='off',
                                    status='pending'
                                )
                    
                    # Log emergency shutdown
                    ActivityLog.log_user_action(
                        user=user,
                        message='Emergency shutdown initiated',
                        details=f'All devices turned off ({devices.count()} devices affected)',
                        source='mobile',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    
                    return Response({
                        'message': f'Emergency shutdown initiated for {devices.count()} devices'
                    }, status=status.HTTP_200_OK)
                
                elif action == 'system_reset':
                    # Clear unresolved alerts and reset system state
                    DeviceAlert.objects.filter(
                        device__owner=user,
                        is_resolved=False
                    ).update(is_resolved=True)
                    
                    # Log system reset
                    ActivityLog.log_user_action(
                        user=user,
                        message='Manual system reset performed',
                        details='All alerts cleared and system reset',
                        source='mobile',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    
                    return Response({
                        'message': 'System reset completed successfully'
                    }, status=status.HTTP_200_OK)
                
                else:
                    return Response(
                        {'error': 'Invalid action. Use "shutdown_all" or "system_reset"'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class AlertDismissalView(APIView):
    def post(self, request, format=None):
        """Dismiss an alert"""
        try:
            email = request.data.get('email')
            alert_id = request.data.get('alert_id')
            
            if not email or not alert_id:
                return Response(
                    {'error': 'Email and alert_id are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                alert = DeviceAlert.objects.get(
                    id=alert_id,
                    device__owner=user
                )
                
                alert.is_resolved = True
                alert.save()
                
                return Response({
                    'message': 'Alert dismissed successfully'
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except DeviceAlert.DoesNotExist:
                return Response(
                    {'error': 'Alert not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )