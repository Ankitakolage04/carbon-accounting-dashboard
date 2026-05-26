from django.test import TestCase
from decimal import Decimal
from datetime import date
from .models import Tenant, PlantLookup, FacilityLookup, IngestedRow, NormalizedData, AuditTrail
from .parsers import (
    process_sap_row, process_utility_row, process_travel_row,
    recalculate_normalized_data, haversine_distance
)

class CarbonAccountingTestCase(TestCase):
    def setUp(self):
        # Create a test tenant
        self.tenant = Tenant.objects.create(name="Acme Corp")
        
        # Setup lookup data
        self.plant = PlantLookup.objects.create(
            tenant=self.tenant,
            plant_code="DE01",
            name="Munich Assembly",
            location="Munich",
            country="DE",
            grid_emission_factor=Decimal("0.35")
        )
        
        self.facility = FacilityLookup.objects.create(
            tenant=self.tenant,
            account_number="ACC123",
            meter_number="MET456",
            name="Boston Data Center",
            location="Boston, MA",
            country="US",
            grid_emission_factor=Decimal("0.25")
        )

    def test_haversine_distance(self):
        # Distance between JFK (40.6398, -73.7789) and LHR (51.4700, -0.4543)
        # Should be approximately 5570 km
        dist = haversine_distance(40.6398, -73.7789, 51.4700, -0.4543)
        self.assertAlmostEqual(dist, 5570.26, delta=50)

    def test_process_sap_row_valid(self):
        # Test valid diesel fuel procurement row
        row_data = {
            'BUDAT': '2026-05-01',
            'MENGE': '1000',
            'MEINS': 'L',
            'WERKS': 'DE01',
            'WRBTR': '1500', # 1.50 EUR/L (within €0.40 - €4.50 bounds)
            'WAERS': 'EUR',
            'MATNR': 'MAT-FUEL-01',
            'MAKTX': 'DIESEL FUEL FOR FORKLIFTS'
        }
        
        row = process_sap_row(row_data, self.tenant, "TestUser")
        self.assertEqual(row.status, 'PENDING')
        self.assertEqual(len(row.validation_errors), 0)
        
        # Check normalized record
        norm = NormalizedData.objects.get(source_row=row)
        self.assertEqual(norm.scope, 'SCOPE_1')
        self.assertEqual(norm.category, 'Fuel - Diesel')
        self.assertEqual(norm.normalized_quantity, Decimal('1000.0000'))
        # 1000 Liters * 2.68 kg CO2e/L = 2680 kg CO2e
        self.assertEqual(norm.co2e_kg, Decimal('2680.0000'))
        
        # Check Audit Trail
        audit = AuditTrail.objects.filter(source_row=row, action='INGEST').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.new_status, 'PENDING')

    def test_process_sap_row_suspicious_plant(self):
        # Unknown plant code should trigger SUSPICIOUS status
        row_data = {
            'BUDAT': '2026-05-01',
            'MENGE': '500',
            'MEINS': 'L',
            'WERKS': 'DE99', # Unknown plant
            'WRBTR': '750',
            'MAKTX': 'DIESEL'
        }
        
        row = process_sap_row(row_data, self.tenant, "TestUser")
        self.assertEqual(row.status, 'SUSPICIOUS')
        self.assertIn("Unknown Plant code: 'DE99'", row.validation_errors[0])
        
        # It still computes normalized data for Draft review!
        norm = NormalizedData.objects.get(source_row=row)
        self.assertEqual(norm.co2e_kg, Decimal('500') * Decimal('2.68'))

    def test_process_sap_row_suspicious_price(self):
        # Exorbitant price per liter should trigger SUSPICIOUS status
        row_data = {
            'BUDAT': '2026-05-01',
            'MENGE': '10',
            'MEINS': 'L',
            'WERKS': 'DE01',
            'WRBTR': '100', # 10.00 EUR/L (Suspiciously high)
            'MAKTX': 'DIESEL'
        }
        
        row = process_sap_row(row_data, self.tenant, "TestUser")
        self.assertEqual(row.status, 'SUSPICIOUS')
        self.assertTrue(any("Suspicious price per unit" in err for err in row.validation_errors))

    def test_process_utility_row_valid(self):
        row_data = {
            'Account_Number': 'ACC123',
            'Meter_Number': 'MET456',
            'Start_Date': '2026-04-01',
            'End_Date': '2026-05-01', # 30 days
            'Usage_kWh': '10000',
            'Total_Amount': '1200', # $0.12/kWh (valid)
            'Currency': 'USD'
        }
        
        row = process_utility_row(row_data, self.tenant, "TestUser")
        self.assertEqual(row.status, 'PENDING')
        self.assertEqual(len(row.validation_errors), 0)
        
        # Verify normalized record
        norm = NormalizedData.objects.get(source_row=row)
        self.assertEqual(norm.scope, 'SCOPE_2')
        # 10000 kWh * 0.25 kg CO2e/kWh (grid factor for Boston) = 2500 kg CO2e
        self.assertEqual(norm.co2e_kg, Decimal('2500.0000'))
        
        # Verify date midpoint calculation
        # Midpoint of April 1st to May 1st (30 days) is April 16th
        self.assertEqual(norm.activity_date, date(2026, 4, 16))

    def test_process_utility_row_overlap(self):
        # Create first valid billing cycle
        first_row_data = {
            'Account_Number': 'ACC123',
            'Meter_Number': 'MET456',
            'Start_Date': '2026-04-01',
            'End_Date': '2026-05-01',
            'Usage_kWh': '10000',
            'Total_Amount': '1200'
        }
        process_utility_row(first_row_data, self.tenant, "TestUser")
        
        # Ingest second row that overlaps
        overlapping_row_data = {
            'Account_Number': 'ACC123',
            'Meter_Number': 'MET456',
            'Start_Date': '2026-04-20', # overlaps!
            'End_Date': '2026-05-20',
            'Usage_kWh': '5000',
            'Total_Amount': '600'
        }
        row = process_utility_row(overlapping_row_data, self.tenant, "TestUser")
        self.assertEqual(row.status, 'SUSPICIOUS')
        self.assertTrue(any("overlaps with existing row" in err for err in row.validation_errors))

    def test_process_travel_row_flight_distance_fallback(self):
        # Flight with missing distance, should fallback to coordinate great-circle distance (JFK -> LHR)
        row_data = {
            'booking_id': 'FL-9988',
            'employee_id': 'EMP001',
            'booking_type': 'flight',
            'departure_airport': 'JFK',
            'arrival_airport': 'LHR',
            'cabin_class': 'Business',
            'departure_date': '2026-05-15',
            'cost': '1800',
            'currency': 'USD'
        }
        
        row = process_travel_row(row_data, self.tenant, "TestUser")
        self.assertEqual(row.status, 'SUSPICIOUS') # suspicious because of distance interpolation warning
        self.assertTrue(any("Distance missing. Calculated JFK-LHR distance" in err for err in row.validation_errors))
        
        # Verify normalized record
        norm = NormalizedData.objects.get(source_row=row)
        # JFK-LHR distance is ~5570 km. Business class factor for long-haul is 0.32 kg CO2e / km
        # 5570 km * 0.32 ~ 1782 kg CO2e
        self.assertTrue(norm.co2e_kg > Decimal('1700') and norm.co2e_kg < Decimal('1900'))

    def test_recalculate_edited_row(self):
        # Ingest a row that fails due to bad date format
        row_data = {
            'BUDAT': '26-05-2026', # Invalid (needs YYYY-MM-DD or YYYYMMDD)
            'MENGE': '100',
            'MEINS': 'L',
            'WERKS': 'DE01',
            'WRBTR': '150',
            'MAKTX': 'DIESEL'
        }
        row = process_sap_row(row_data, self.tenant, "TestUser")
        self.assertEqual(row.status, 'FAILED')
        self.assertEqual(NormalizedData.objects.filter(source_row=row).count(), 0)
        
        # Edit the row via the Edit API view
        new_raw_data = row.raw_data.copy()
        new_raw_data['BUDAT'] = '2026-05-26'
        
        response = self.client.post(
            f'/api/v1/ingested-rows/{row.id}/edit/',
            {'raw_data': new_raw_data, 'user_name': 'AnalystUser'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Reload from DB
        row.refresh_from_db()
        self.assertEqual(row.status, 'PENDING')
        self.assertEqual(len(row.validation_errors), 0)
        self.assertEqual(NormalizedData.objects.filter(source_row=row).count(), 1)
        
        # Check audit trail record for edit
        audit = AuditTrail.objects.filter(source_row=row, action='EDIT').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.previous_status, 'FAILED')
        self.assertEqual(audit.new_status, 'PENDING')

