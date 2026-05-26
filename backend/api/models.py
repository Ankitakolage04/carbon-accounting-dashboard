from django.db import models
import uuid

class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    api_key = models.CharField(max_length=255, unique=True, default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class PlantLookup(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="plants")
    plant_code = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    country = models.CharField(max_length=100)  # e.g., "DE", "US", "IN"
    grid_emission_factor = models.DecimalField(max_digits=8, decimal_places=4, default=0.35)  # kg CO2e per kWh or other unit

    class Meta:
        unique_together = (("tenant", "plant_code"),)

    def __str__(self):
        return f"{self.plant_code} - {self.name} ({self.tenant.name})"

class FacilityLookup(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="facilities")
    account_number = models.CharField(max_length=100)
    meter_number = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    country = models.CharField(max_length=100)
    grid_emission_factor = models.DecimalField(max_digits=8, decimal_places=4, default=0.25)  # kg CO2e per kWh

    class Meta:
        unique_together = (("tenant", "account_number", "meter_number"),)

    def __str__(self):
        return f"{self.account_number}/{self.meter_number} - {self.name} ({self.tenant.name})"

class IngestedRow(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved & Locked'),
        ('FAILED', 'Ingestion Failed'),
        ('SUSPICIOUS', 'Suspicious / Flagged'),
    ]

    SOURCE_CHOICES = [
        ('SAP', 'SAP ERP Fuel & Procurement'),
        ('UTILITY', 'Utility Electricity Bill'),
        ('TRAVEL', 'Corporate Travel API'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="ingested_rows")
    source_type = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    raw_data = models.JSONField()
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDING')
    validation_errors = models.JSONField(default=list, blank=True)
    uploaded_by = models.CharField(max_length=255, default='System / API')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.source_type} ({self.status}) - Tenant: {self.tenant.name} - ID: {self.id}"

class NormalizedData(models.Model):
    SCOPE_CHOICES = [
        ('SCOPE_1', 'Scope 1 (Direct)'),
        ('SCOPE_2', 'Scope 2 (Indirect)'),
        ('SCOPE_3', 'Scope 3 (Other Indirect)'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="normalized_data")
    source_row = models.OneToOneField(IngestedRow, on_delete=models.CASCADE, related_name="normalized_record")
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    category = models.CharField(max_length=100)  # e.g., "Fuel - Diesel", "Electricity", "Flight", "Hotel", "Ground Transport"
    activity_date = models.DateField()
    raw_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    raw_unit = models.CharField(max_length=50)
    normalized_quantity = models.DecimalField(max_digits=18, decimal_places=4)  # Liters, kWh, room-nights, passenger-km
    normalized_unit = models.CharField(max_length=50)
    co2e_kg = models.DecimalField(max_digits=18, decimal_places=4)
    source_identifier = models.CharField(max_length=255, blank=True)  # e.g., plant code, meter number, airport codes
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.scope} | {self.category} | {self.co2e_kg} kg CO2e"

class AuditTrail(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="audit_trails")
    source_row = models.ForeignKey(IngestedRow, on_delete=models.CASCADE, related_name="audit_records")
    user = models.CharField(max_length=255, default="System")
    action = models.CharField(max_length=100)  # e.g., "INGEST", "VALIDATE", "EDIT", "APPROVE", "REJECT"
    previous_status = models.CharField(max_length=50, blank=True, null=True)
    new_status = models.CharField(max_length=50)
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} on Row {self.source_row.id} by {self.user} ({self.timestamp})"
