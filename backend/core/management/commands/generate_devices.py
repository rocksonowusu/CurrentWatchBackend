import random
from django.core.management.base import BaseCommand
from core.models import Device, Controller
from django.utils.crypto import get_random_string

class Command(BaseCommand):
    help = 'Generate devices for a specific controller with predefined types'

    def add_arguments(self, parser):
        parser.add_argument('controller_id', type=str, help='Controller ID to create devices for')

    def handle(self, *args, **kwargs):
        controller_id = kwargs['controller_id']
        
        # Check if controller exists, create if not
        controller, created = Controller.objects.get_or_create(
            controller_id=controller_id,
            defaults={
                'name': f'Controller {controller_id[-4:]}',
                'is_online': False
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created new controller: {controller_id}'))
        else:
            self.stdout.write(f'Using existing controller: {controller_id}')

        # Define the exact devices to create
        devices_to_create = [
            {'name': 'kitchen', 'type': 'socket', 'display_name': 'Kitchen Socket'},
            {'name': 'living', 'type': 'socket', 'display_name': 'Living Room Socket'},
            {'name': 'light1', 'type': 'light', 'display_name': 'Light 1'},
            {'name': 'light2', 'type': 'light', 'display_name': 'Light 2'},
            {'name': 'fan', 'type': 'fan', 'display_name': 'Ceiling Fan'}
        ]

        created_count = 0
        
        for device_info in devices_to_create:
            device_id = f"{controller_id}-{device_info['name']}"
            
            # Check if device already exists
            if Device.objects.filter(device_id=device_id).exists():
                self.stdout.write(f'Device {device_id} already exists, skipping...')
                continue

            
            device = Device.objects.create(
                device_id=device_id,
                name=device_info['display_name'],
                type=device_info['type'],
                controller=controller,
                hardware_pin=device_info['name'],
                pairing_code=get_random_string(6, '0123456789'),
                is_paired=False
            )
            
            created_count += 1
            self.stdout.write(f'Created: {device.name} ({device.device_id}) - Code: {device.pairing_code}')

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} devices for controller {controller_id}')
        )
        
        if created_count > 0:
            self.stdout.write(
                self.style.WARNING('Devices are unassigned. Pair them through the mobile app or admin interface.')
            )