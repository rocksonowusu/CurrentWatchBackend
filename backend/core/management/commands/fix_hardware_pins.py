from django.core.management.base import BaseCommand
from core.models import Device, Controller
from django.db import transaction

class Command(BaseCommand):
    help = 'Fix hardware_pin values for existing devices'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Find devices with missing or incorrect hardware_pin
        devices_to_fix = Device.objects.filter(hardware_pin__isnull=True)
        devices_with_pins = Device.objects.exclude(hardware_pin__isnull=True)
        
        self.stdout.write(f'Found {devices_to_fix.count()} devices with missing hardware_pin')
        self.stdout.write(f'Found {devices_with_pins.count()} devices with hardware_pin set')
        
        fixed_count = 0
        
        with transaction.atomic():
            for device in devices_to_fix:
                if device.device_id:
                    parts = device.device_id.split('-')
                    if len(parts) > 2:
                        hardware_pin = parts[-1]
                        
                        self.stdout.write(f'Fixing {device.device_id}: setting hardware_pin to "{hardware_pin}"')
                        
                        if not dry_run:
                            device.hardware_pin = hardware_pin
                            device.save()
                        
                        fixed_count += 1
        
        # Check for potential conflicts
        self.stdout.write('\n--- Checking for potential conflicts ---')
        controllers = Controller.objects.all()
        
        for controller in controllers:
            controller_devices = Device.objects.filter(controller=controller).exclude(hardware_pin__isnull=True)
            pins = [d.hardware_pin for d in controller_devices]
            
            # Check for duplicates
            duplicates = set([pin for pin in pins if pins.count(pin) > 1])
            if duplicates:
                self.stdout.write(
                    self.style.ERROR(
                        f'Controller {controller.controller_id} has duplicate hardware pins: {duplicates}'
                    )
                )
                
                for pin in duplicates:
                    conflicting_devices = controller_devices.filter(hardware_pin=pin)
                    for i, device in enumerate(conflicting_devices):
                        self.stdout.write(f'  - {device.name} ({device.device_id})')
                        if i > 0:  # Keep first one, suggest fix for others
                            suggested_pin = f"{pin}_alt_{i}"
                            self.stdout.write(
                                self.style.WARNING(f'    Suggest changing to: {suggested_pin}')
                            )
        
        # Summary
        self.stdout.write('\n--- Summary ---')
        if dry_run:
            self.stdout.write(f'Would fix {fixed_count} devices')
        else:
            self.stdout.write(self.style.SUCCESS(f'Fixed {fixed_count} devices'))
        
        # Show current state
        self.stdout.write('\n--- Current Device State ---')
        all_devices = Device.objects.all().order_by('controller__controller_id', 'hardware_pin')
        
        current_controller = None
        for device in all_devices:
            if device.controller != current_controller:
                current_controller = device.controller
                controller_name = current_controller.controller_id if current_controller else "No Controller"
                self.stdout.write(f'\n{controller_name}:')
            
            status = "✓ Paired" if device.is_paired else "○ Unpaired"
            hardware_pin = device.hardware_pin or "❌ MISSING"
            
            self.stdout.write(f'  {device.name} | Pin: {hardware_pin} | {status}')
        
        # Recommendations
        self.stdout.write('\n--- Recommendations ---')
        if devices_to_fix.count() > 0:
            if dry_run:
                self.stdout.write('Run this command without --dry-run to fix missing hardware pins')
            else:
                self.stdout.write('Missing hardware pins have been fixed')
        
        unpaired_devices = Device.objects.filter(is_paired=False)
        if unpaired_devices.count() > 0:
            self.stdout.write(f'{unpaired_devices.count()} devices are unpaired and ready for pairing')
        
        paired_no_controller = Device.objects.filter(is_paired=True, controller__isnull=True)
        if paired_no_controller.count() > 0:
            self.stdout.write(
                self.style.ERROR(f'{paired_no_controller.count()} paired devices have no controller - this will cause command failures')
            )
            for device in paired_no_controller:
                self.stdout.write(f'  - {device.name} ({device.device_id})')
        
        self.stdout.write('\n--- ESP32 Communication Check ---')
        paired_devices = Device.objects.filter(is_paired=True, controller__isnull=False)
        self.stdout.write(f'Devices ready for ESP32 commands: {paired_devices.count()}')
        
        for device in paired_devices:
            if device.hardware_pin:
                self.stdout.write(f'  ✓ {device.name} -> ESP32 uses "{device.hardware_pin}"')
            else:
                self.stdout.write(f'  ❌ {device.name} -> Missing hardware_pin!')