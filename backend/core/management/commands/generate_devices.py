import random
from django.core.management.base import BaseCommand
from core.models import Device
from django.utils.crypto import get_random_string

class Command(BaseCommand):
    help = 'Generate unassigned devices with random IDs and pairing codes'

    def add_arguments(self, parser):
        parser.add_argument('count', type=int, help='Number of devices to create')

    def handle(self, *args, **kwargs):
        count = kwargs['count']
        created = 0

        for _ in range(count):
            device_id = get_random_string(12).upper()
            pairing_code = get_random_string(6, '0123456789')

            if Device.objects.filter(device_id=device_id).exists():
                continue  # avoid duplicates

            device = Device.objects.create(
                device_id=device_id,
                name="New Device",
                type=random.choice(['socket', 'light', 'fan']),
                pairing_code=pairing_code,
                is_paired=False
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully created {created} devices'))
