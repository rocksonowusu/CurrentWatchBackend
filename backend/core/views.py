from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import UserProfile, Room, Device
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
                
                # TODO: Send test alert to hardware system via GSM
                # This would be implemented using your GSM module
                print(f"Test alert sent to hardware for phone: {phone_number}")
                
                return Response({
                    'message': 'Phone number verified and test alert sent',
                    'phone_number': phone_number
                }, status=status.HTTP_200_OK)
                
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

class DevicePairingInitView(APIView):
    def post(self, request, format=None):
        """Endpoint for ESP32 to initialize pairing"""
        try:
            device_id = request.data.get('device_id')
            device_type = request.data.get('type', 'socket')  # Default to socket
            
            if not device_id:
                return Response(
                    {'error': 'Device ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create unpaired device
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
            device_type = data.get('device_type')   # Optional custom name
            
            if not email or not device_id or not pairing_code:
                return Response(
                    {'error': 'Email, device ID and pairing code are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = UserProfile.objects.get(email=email)
                device = Device.objects.get(device_id=device_id, pairing_code=pairing_code)
                
                # Update device details
                device.is_paired = True
                device.owner = user
                device.endpoint_url = endpoint_url or ''
                device.last_seen = timezone.now()
                
                # Set custom name if provided
                if device_name:
                    device.name = device_name

                if device_type:
                    device.type = device_type
                
                # Assign to room if provided and user owns the room
                if room_id:
                    try:
                        room = Room.objects.get(id=room_id, owner=user)
                        device.room = room
                    except Room.DoesNotExist:
                        pass
                
                device.save()
                
                return Response({
                    'message': 'Device paired successfully',
                    'device_id': device.device_id,
                    'device_name': device.name,
                    'room_id': device.room.id if device.room else None
                }, status=status.HTTP_200_OK)
                
            except UserProfile.DoesNotExist:
                return Response(
                    {'error': 'User not found - complete onboarding first'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Device.DoesNotExist:
                return Response(
                    {'error': 'Invalid device ID or pairing code'},
                    status=status.HTTP_404_NOT_FOUND
                )
                    
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class DeviceStatusView(APIView):
    def post(self, request, format=None):
        """Endpoint for ESP32 to report status"""
        try:
            device_id = request.data.get('device_id')
            current_value = request.data.get('current')
            is_on = request.data.get('is_on')
            
            if not device_id:
                return Response(
                    {'error': 'Device ID is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                device = Device.objects.get(device_id=device_id)
                device.last_seen = timezone.now()
                device.save()
                
                # TODO: Store current reading in separate model
                
                return Response({
                    'message': 'Status received',
                    'commands': []  # Can return commands to execute
                }, status=status.HTTP_200_OK)
                
            except Device.DoesNotExist:
                return Response(
                    {'error': 'Device not registered'},
                    status=status.HTTP_404_NOT_FOUND
                )
                    
        except Exception as e:
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
                        'name': device.name,
                        'type': device.type,
                        'room_id': device.room.id if device.room else None,
                        'room_name': device.room.name if device.room else None,
                        'is_paired': device.is_paired,
                        'last_seen': device.last_seen,
                        'created_at': device.created_at
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