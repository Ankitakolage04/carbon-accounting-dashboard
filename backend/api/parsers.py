import math
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from django.db.models import Q
from .models import IngestedRow, NormalizedData, AuditTrail, PlantLookup, FacilityLookup

# Airport Coordinates Lookup for Haversine Distance Fallback
AIRPORT_COORDINATES = {
    'JFK': (40.6398, -73.7789),
    'LHR': (51.4700, -0.4543),
    'LAX': (33.9416, -118.4085),
    'CDG': (49.0097, 2.5479),
    'DXB': (25.2532, 55.3657),
    'SIN': (1.3644, 103.9915),
    'SYD': (-33.9461, 151.1772),
    'BOM': (19.0896, 72.8656),
    'DEL': (28.5665, 77.1031),
    'FRA': (50.0379, 8.5622),
}

# Emission Factors (in kg CO2e per unit)
EMISSION_FACTORS = {
    'FUEL_DIESEL_L': Decimal('2.68'),        # kg CO2e / Liter
    'FUEL_PETROL_L': Decimal('2.31'),        # kg CO2e / Liter
    'PROCUREMENT_DEFAULT': Decimal('0.12'),  # kg CO2e / $ spend (Scope 3)
    
    # Grid Electricity emission factors (fallback default - in kg CO2e / kWh)
    'GRID_DEFAULT': Decimal('0.35'),
    
    # Travel Emission Factors (in kg CO2e per passenger-kilometer or room-night)
    'FLIGHT_SHORT_HAUL_ECONOMY': Decimal('0.15'),  # < 500 km
    'FLIGHT_SHORT_HAUL_BUSINESS': Decimal('0.22'),
    'FLIGHT_LONG_HAUL_ECONOMY': Decimal('0.11'),   # >= 500 km
    'FLIGHT_LONG_HAUL_BUSINESS': Decimal('0.32'),
    
    # Hotel room night by country (kg CO2e / night)
    'HOTEL_US': Decimal('20.4'),
    'HOTEL_DE': Decimal('14.8'),
    'HOTEL_IN': Decimal('32.1'),
    'HOTEL_GB': Decimal('15.2'),
    'HOTEL_DEFAULT': Decimal('18.0'),
    
    # Ground Transport (kg CO2e / km)
    'GROUND_CAR_PETROL': Decimal('0.18'),
    'GROUND_CAR_DIESEL': Decimal('0.17'),
    'GROUND_CAR_ELECTRIC': Decimal('0.04'),
    'GROUND_CAR_HYBRID': Decimal('0.11'),
    'GROUND_TAXI': Decimal('0.22'),
    'GROUND_TRAIN': Decimal('0.03'),
}

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates the great-circle distance in kilometers between two points."""
    R = 6371.0  # Earth's radius in kilometers
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def safe_decimal(val, default=Decimal('0.00')):
    """Safely converts a value to Decimal."""
    if val is None or str(val).strip() == '':
        return default
    try:
        # Remove currency symbols or commas if present
        clean_val = str(val).replace('$', '').replace('€', '').replace(',', '').strip()
        return Decimal(clean_val)
    except (InvalidOperation, ValueError):
        return default

def parse_date(date_str):
    """Parse dates in various common formats (YYYYMMDD, YYYY-MM-DD, DD/MM/YYYY)."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    for fmt in ('%Y%m%d', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None

def process_sap_row(row_data, tenant, user_name='System'):
    """
    Processes a single SAP row.
    Expected keys (German and English aliases supported):
    - BUDAT / Posting_Date
    - MENGE / Quantity
    - MEINS / Unit
    - WERKS / Plant
    - WRBTR / Amount
    - WAERS / Currency
    - MATNR / Material_Number
    - MAKTX / Material_Description
    """
    # Header Mapping
    posting_date_raw = row_data.get('BUDAT') or row_data.get('Posting_Date') or row_data.get('posting_date')
    quantity_raw = row_data.get('MENGE') or row_data.get('Quantity') or row_data.get('quantity')
    unit_raw = row_data.get('MEINS') or row_data.get('Unit') or row_data.get('unit')
    plant_raw = row_data.get('WERKS') or row_data.get('Plant') or row_data.get('plant')
    amount_raw = row_data.get('WRBTR') or row_data.get('Amount') or row_data.get('amount')
    currency_raw = row_data.get('WAERS') or row_data.get('Currency') or row_data.get('currency') or 'EUR'
    matnr_raw = row_data.get('MATNR') or row_data.get('Material_Number') or row_data.get('material_number')
    maktx_raw = row_data.get('MAKTX') or row_data.get('Material_Description') or row_data.get('material_description') or ''
    
    validation_errors = []
    status = 'PENDING'
    
    # 1. Parse Date
    activity_date = parse_date(posting_date_raw)
    if not activity_date:
        validation_errors.append(f"Invalid posting date format: '{posting_date_raw}'")
        status = 'FAILED'
        
    # 2. Parse Quantity
    qty = safe_decimal(quantity_raw)
    if qty <= 0:
        validation_errors.append(f"Negative or zero quantity: {qty}")
        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
        
    # 3. Check Unit
    unit = str(unit_raw).strip().upper() if unit_raw else ''
    if unit not in ['L', 'GAL', 'KG', 'LIT']:
        # If it's a non-fuel item, maybe it's PC (Pieces) or EA (Each)
        if unit not in ['PC', 'EA', 'ST']: # ST is German for pieces
            validation_errors.append(f"Uncommon Unit of Measure: '{unit}'")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
    # 4. Check Plant
    plant_code = str(plant_raw).strip() if plant_raw else ''
    plant_lookup = None
    if not plant_code:
        validation_errors.append("Plant code is missing")
        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
    else:
        plant_lookup = PlantLookup.objects.filter(tenant=tenant, plant_code=plant_code).first()
        if not plant_lookup:
            validation_errors.append(f"Unknown Plant code: '{plant_code}'")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'

    # 5. Check cost anomalies
    cost = safe_decimal(amount_raw)
    if cost < 0:
        validation_errors.append(f"Negative cost amount: {cost}")
        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
        
    if qty > 0 and cost > 0:
        price_per_unit = cost / qty
        # Fuel price anomaly detection (e.g. Diesel price in EUR/L should be between 0.5 and 5.0)
        if "DIESEL" in maktx_raw.upper() or "HEIZOEL" in maktx_raw.upper():
            if price_per_unit < Decimal('0.40') or price_per_unit > Decimal('4.50'):
                validation_errors.append(f"Suspicious price per unit: {price_per_unit:.2f} {currency_raw}/L (out of normal range €0.40-€4.50/L)")
                status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                
    # Ingestion record creation
    ingested_row = IngestedRow.objects.create(
        tenant=tenant,
        source_type='SAP',
        raw_data=row_data,
        status=status,
        validation_errors=validation_errors,
        uploaded_by=user_name
    )
    
    # Audit Trail for Ingestion
    AuditTrail.objects.create(
        tenant=tenant,
        source_row=ingested_row,
        user=user_name,
        action='INGEST',
        previous_status=None,
        new_status=status,
        details={'validation_errors': validation_errors}
    )
    
    # 6. Normalize & Compute Emissions (only if status is not FAILED)
    if status != 'FAILED' and activity_date:
        # Determine emission scope & category
        maktx_upper = maktx_raw.upper()
        if 'DIESEL' in maktx_upper or 'HEIZOEL' in maktx_upper:
            category = 'Fuel - Diesel'
            scope = 'SCOPE_1'
            # Convert units to Liters
            if unit == 'GAL':
                normalized_qty = qty * Decimal('3.78541')
                normalized_unit = 'L'
            else:
                normalized_qty = qty
                normalized_unit = 'L'
            co2e_factor = EMISSION_FACTORS['FUEL_DIESEL_L']
            co2e_kg = normalized_qty * co2e_factor
        elif 'PETROL' in maktx_upper or 'GASOLINE' in maktx_upper or 'BENZIN' in maktx_upper:
            category = 'Fuel - Petrol'
            scope = 'SCOPE_1'
            if unit == 'GAL':
                normalized_qty = qty * Decimal('3.78541')
                normalized_unit = 'L'
            else:
                normalized_qty = qty
                normalized_unit = 'L'
            co2e_factor = EMISSION_FACTORS['FUEL_PETROL_L']
            co2e_kg = normalized_qty * co2e_factor
        else:
            # General procurement (Scope 3 Purchased Goods & Services)
            category = 'Procurement - Purchased Goods'
            scope = 'SCOPE_3'
            normalized_qty = cost
            normalized_unit = currency_raw
            # Spend-based emission method: €1 spend ~ 0.12 kg CO2e (simplified fallback)
            co2e_factor = EMISSION_FACTORS['PROCUREMENT_DEFAULT']
            co2e_kg = normalized_qty * co2e_factor
            
        description = f"SAP Ingest: Material {matnr_raw} ({maktx_raw}). Cost: {cost} {currency_raw}."
        if plant_lookup:
            description += f" Plant: {plant_lookup.name} ({plant_lookup.location}, {plant_lookup.country})."
            
        NormalizedData.objects.create(
            tenant=tenant,
            source_row=ingested_row,
            scope=scope,
            category=category,
            activity_date=activity_date,
            raw_quantity=qty,
            raw_unit=unit,
            normalized_quantity=normalized_qty,
            normalized_unit=normalized_unit,
            co2e_kg=co2e_kg,
            source_identifier=plant_code,
            description=description
        )
        
    return ingested_row

def process_utility_row(row_data, tenant, user_name='System'):
    """
    Processes a single Utility electricity row.
    Expected keys:
    - Account_Number / Account Number
    - Meter_Number / Meter Number
    - Start_Date / Start Date
    - End_Date / End Date
    - Usage_kWh / Consumption
    - Total_Amount / Amount
    - Currency
    - Tariff_Code
    """
    account_num = row_data.get('Account_Number') or row_data.get('Account Number') or row_data.get('account_number')
    meter_num = row_data.get('Meter_Number') or row_data.get('Meter Number') or row_data.get('meter_number')
    start_date_raw = row_data.get('Start_Date') or row_data.get('Start Date') or row_data.get('start_date')
    end_date_raw = row_data.get('End_Date') or row_data.get('End Date') or row_data.get('end_date')
    usage_raw = row_data.get('Usage_kWh') or row_data.get('Consumption') or row_data.get('usage_kwh')
    amount_raw = row_data.get('Total_Amount') or row_data.get('Amount') or row_data.get('amount')
    currency = row_data.get('Currency') or row_data.get('currency') or 'USD'
    tariff = row_data.get('Tariff_Code') or row_data.get('Tariff') or row_data.get('tariff') or 'Standard'
    
    validation_errors = []
    status = 'PENDING'
    
    # 1. Parse Dates
    start_date = parse_date(start_date_raw)
    end_date = parse_date(end_date_raw)
    
    if not start_date or not end_date:
        validation_errors.append(f"Invalid billing dates: Start '{start_date_raw}', End '{end_date_raw}'")
        status = 'FAILED'
    elif start_date >= end_date:
        validation_errors.append(f"Start date ({start_date}) is after or equal to End date ({end_date})")
        status = 'FAILED'
        
    # 2. Parse Usage
    usage = safe_decimal(usage_raw)
    if usage <= 0 and status != 'FAILED':
        validation_errors.append(f"Usage is zero or negative: {usage} kWh")
        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
        
    # 3. Check Meter lookup
    facility = None
    meter_str = str(meter_num).strip() if meter_num else ''
    account_str = str(account_num).strip() if account_num else ''
    
    if not meter_str:
        validation_errors.append("Meter number is missing")
        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
    else:
        facility = FacilityLookup.objects.filter(tenant=tenant, account_number=account_str, meter_number=meter_str).first()
        if not facility:
            validation_errors.append(f"Unknown meter number '{meter_str}' under account '{account_str}'")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
    # 4. Check Date Overlaps
    if start_date and end_date and meter_str:
        # Check database for existing approved or pending utility records for this meter that overlap
        overlapping_rows = IngestedRow.objects.filter(
            tenant=tenant,
            source_type='UTILITY',
            status__in=['PENDING', 'APPROVED']
        ).exclude(
            # Exclude failed or rejected rows, and we can check overlaps in raw_data or normalized
        )
        for ov_row in overlapping_rows:
            ov_start = parse_date(ov_row.raw_data.get('Start_Date') or ov_row.raw_data.get('Start Date'))
            ov_end = parse_date(ov_row.raw_data.get('End_Date') or ov_row.raw_data.get('End Date'))
            ov_meter = ov_row.raw_data.get('Meter_Number') or ov_row.raw_data.get('Meter Number')
            
            if ov_start and ov_end and str(ov_meter).strip() == meter_str:
                # Check overlap: (start1 < end2) and (start2 < end1)
                if start_date < ov_end and ov_start < end_date:
                    validation_errors.append(f"Billing period overlaps with existing row ID {ov_row.id} ({ov_start} to {ov_end})")
                    status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                    break
                    
    # 5. Check billing duration (normal is 28-33 days)
    if start_date and end_date:
        duration = (end_date - start_date).days
        if duration < 20 or duration > 40:
            validation_errors.append(f"Billing period duration of {duration} days is outside normal bounds (20-40 days)")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
    # 6. Check Rate anomalies
    cost = safe_decimal(amount_raw)
    if cost <= 0:
        validation_errors.append(f"Billing cost amount is negative or zero: {cost}")
        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
        
    if usage > 0 and cost > 0:
        rate_per_kwh = cost / usage
        if rate_per_kwh < Decimal('0.02') or rate_per_kwh > Decimal('0.60'):
            validation_errors.append(f"Suspicious electricity rate: {rate_per_kwh:.3f} {currency}/kWh (out of normal range $0.02-$0.60/kWh)")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
    # Ingestion record creation
    ingested_row = IngestedRow.objects.create(
        tenant=tenant,
        source_type='UTILITY',
        raw_data=row_data,
        status=status,
        validation_errors=validation_errors,
        uploaded_by=user_name
    )
    
    # Audit Trail for Ingestion
    AuditTrail.objects.create(
        tenant=tenant,
        source_row=ingested_row,
        user=user_name,
        action='INGEST',
        previous_status=None,
        new_status=status,
        details={'validation_errors': validation_errors}
    )
    
    # 7. Normalize & Compute Emissions (only if status is not FAILED)
    if status != 'FAILED' and start_date and end_date:
        # Calculate midpoint of billing period to use as activity_date
        duration = (end_date - start_date).days
        midpoint_delta = duration // 2
        activity_date = start_date + timedelta(days=midpoint_delta)
        
        # Grid factor (location-based Scope 2)
        grid_factor = facility.grid_emission_factor if facility else EMISSION_FACTORS['GRID_DEFAULT']
        co2e_kg = usage * grid_factor
        
        description = f"Utility Electricity Ingest: Account {account_str}, Meter {meter_str}. Billing: {start_date} to {end_date} ({duration} days). Cost: {cost} {currency}."
        if facility:
            description += f" Facility: {facility.name} ({facility.location}, {facility.country})."
            
        NormalizedData.objects.create(
            tenant=tenant,
            source_row=ingested_row,
            scope='SCOPE_2',
            category='Electricity',
            activity_date=activity_date,
            raw_quantity=usage,
            raw_unit='kWh',
            normalized_quantity=usage,
            normalized_unit='kWh',
            co2e_kg=co2e_kg,
            source_identifier=meter_str,
            description=description
        )
        
    return ingested_row



def process_travel_row(row_data, tenant, user_name='System'):
    """
    Processes a single travel booking (flights, hotels, ground transport).
    Expected keys:
    - booking_id
    - employee_id
    - booking_type ('flight', 'hotel', 'ground')
    - departure_airport / arrival_airport (for flight)
    - distance_miles / distance_km (for flight/ground)
    - cabin_class (for flight: Economy, Business, First)
    - departure_date / travel_date
    - check_in_date / check_out_date (for hotel)
    - hotel_name / city / country (for hotel)
    - number_of_nights / number_of_rooms (for hotel)
    - transport_type / fuel_type (for ground)
    - cost
    - currency
    """
    booking_id = row_data.get('booking_id')
    booking_type = str(row_data.get('booking_type')).strip().lower() if row_data.get('booking_type') else ''
    cost_raw = row_data.get('cost')
    currency = row_data.get('currency') or 'USD'
    
    validation_errors = []
    status = 'PENDING'
    
    if not booking_id:
        validation_errors.append("Travel Booking ID is missing")
        status = 'FAILED'
        
    if booking_type not in ['flight', 'hotel', 'ground']:
        validation_errors.append(f"Invalid corporate travel booking type: '{booking_type}'")
        status = 'FAILED'
        
    cost = safe_decimal(cost_raw)
    if cost < 0:
        validation_errors.append(f"Negative booking cost amount: {cost}")
        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
        
    # 1. Processing Specific Types
    activity_date = None
    normalized_qty = Decimal('0.00')
    normalized_unit = ''
    co2e_kg = Decimal('0.00')
    category = ''
    scope = 'SCOPE_3'  # corporate business travel is Scope 3, Category 6
    source_identifier = ''
    description = ''
    
    if status != 'FAILED':
        if booking_type == 'flight':
            dep_airport = str(row_data.get('departure_airport', '')).strip().upper()
            arr_airport = str(row_data.get('arrival_airport', '')).strip().upper()
            cabin = str(row_data.get('cabin_class', 'Economy')).strip().capitalize()
            travel_date_raw = row_data.get('departure_date') or row_data.get('travel_date')
            
            activity_date = parse_date(travel_date_raw)
            if not activity_date:
                validation_errors.append(f"Invalid flight departure date format: '{travel_date_raw}'")
                status = 'FAILED'
                
            if not dep_airport or not arr_airport:
                validation_errors.append("Departure and/or arrival airports are missing for flight")
                status = 'FAILED'
                
            dist_km = Decimal('0.00')
            dist_raw = row_data.get('distance_km') or row_data.get('distance_miles')
            
            # Distance fallback calculation
            if not dist_raw and status != 'FAILED':
                if dep_airport in AIRPORT_COORDINATES and arr_airport in AIRPORT_COORDINATES:
                    coord1 = AIRPORT_COORDINATES[dep_airport]
                    coord2 = AIRPORT_COORDINATES[arr_airport]
                    calculated_dist = haversine_distance(coord1[0], coord1[1], coord2[0], coord2[1])
                    dist_km = Decimal(str(calculated_dist))
                    validation_errors.append(f"Distance missing. Calculated {dep_airport}-{arr_airport} distance of {dist_km:.2f} km using Haversine fallback.")
                    # Keep status as suspicious to alert the user that distance was interpolated
                    status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                else:
                    validation_errors.append(f"Distance missing and airport coordinates not in lookup for '{dep_airport}' to '{arr_airport}'")
                    status = 'FAILED'
            elif dist_raw:
                # If distance is provided, check if it's km or miles
                dist_val = safe_decimal(dist_raw)
                if 'miles' in row_data or 'distance_miles' in row_data:
                    dist_km = dist_val * Decimal('1.60934')
                else:
                    dist_km = dist_val
                    
            if dist_km <= 0 and status != 'FAILED':
                validation_errors.append(f"Flight distance is negative or zero: {dist_km} km")
                status = 'FAILED'
                
            if status != 'FAILED':
                # Cabin class emission factor
                # Shorthaul vs Longhaul threshold (500 km)
                is_short = dist_km < Decimal('500.00')
                if cabin not in ['Economy', 'Premium economy', 'Business', 'First']:
                    validation_errors.append(f"Unknown flight cabin class: '{cabin}'. Defaulted multiplier to Economy.")
                    status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                    cabin = 'Economy'
                    
                if is_short:
                    factor = EMISSION_FACTORS['FLIGHT_SHORT_HAUL_BUSINESS'] if cabin in ['Business', 'First'] else EMISSION_FACTORS['FLIGHT_SHORT_HAUL_ECONOMY']
                else:
                    factor = EMISSION_FACTORS['FLIGHT_LONG_HAUL_BUSINESS'] if cabin in ['Business', 'First'] else EMISSION_FACTORS['FLIGHT_LONG_HAUL_ECONOMY']
                    
                co2e_kg = dist_km * factor
                normalized_qty = dist_km
                normalized_unit = 'km'
                category = 'Business Travel - Flight'
                source_identifier = f"{dep_airport}-{arr_airport}"
                description = f"Flight: {dep_airport} to {arr_airport} ({cabin} class). Distance: {dist_km:.2f} km. Cost: {cost} {currency}."
                
        elif booking_type == 'hotel':
            checkin_raw = row_data.get('check_in_date')
            checkout_raw = row_data.get('check_out_date')
            country = str(row_data.get('country', 'US')).strip().upper()
            hotel_name = row_data.get('hotel_name', 'Unknown Hotel')
            rooms = int(row_data.get('number_of_rooms') or 1)
            nights_raw = row_data.get('number_of_nights')
            
            activity_date = parse_date(checkin_raw)
            if not activity_date:
                validation_errors.append(f"Invalid hotel check-in date format: '{checkin_raw}'")
                status = 'FAILED'
                
            checkout_date = parse_date(checkout_raw)
            nights = 0
            if activity_date and checkout_date:
                nights = (checkout_date - activity_date).days
                if nights <= 0:
                    validation_errors.append(f"Hotel checkout date ({checkout_date}) is before or equal to check-in ({activity_date})")
                    status = 'FAILED'
            elif nights_raw:
                nights = int(nights_raw)
                
            if nights <= 0 and status != 'FAILED':
                validation_errors.append(f"Invalid number of nights: {nights}")
                status = 'FAILED'
                
            if rooms <= 0 and status != 'FAILED':
                validation_errors.append(f"Invalid number of rooms: {rooms}")
                status = 'FAILED'
                
            if status != 'FAILED':
                # Country-specific factors
                factor_key = f"HOTEL_{country}"
                factor = EMISSION_FACTORS.get(factor_key, EMISSION_FACTORS['HOTEL_DEFAULT'])
                
                room_nights = Decimal(str(nights * rooms))
                co2e_kg = room_nights * factor
                normalized_qty = room_nights
                normalized_unit = 'room-nights'
                category = 'Business Travel - Hotel'
                source_identifier = country
                description = f"Hotel Night: {hotel_name} in {country}. Rooms: {rooms}, Nights: {nights}. Cost: {cost} {currency}."
                
                if cost > 0 and room_nights > 0:
                    cost_per_night = cost / room_nights
                    if cost_per_night < Decimal('10.00') or cost_per_night > Decimal('1000.00'):
                        validation_errors.append(f"Suspicious hotel rate: {cost_per_night:.2f} {currency}/night (out of normal range $10-$1000)")
                        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                        
        elif booking_type == 'ground':
            transport_type = str(row_data.get('transport_type')).strip().lower() if row_data.get('transport_type') else ''
            fuel_type = str(row_data.get('fuel_type', 'Petrol')).strip().capitalize()
            travel_date_raw = row_data.get('travel_date') or row_data.get('departure_date')
            dist_raw = row_data.get('distance_km') or row_data.get('distance_miles')
            
            activity_date = parse_date(travel_date_raw)
            if not activity_date:
                validation_errors.append(f"Invalid travel date: '{travel_date_raw}'")
                status = 'FAILED'
                
            dist_val = safe_decimal(dist_raw)
            if dist_val <= 0 and status != 'FAILED':
                validation_errors.append(f"Ground travel distance is negative or zero: {dist_val}")
                status = 'FAILED'
                
            if transport_type not in ['rental car', 'rental_car', 'car rental', 'car_rental', 'taxi', 'train', 'rail']:
                validation_errors.append(f"Uncommon transport type: '{transport_type}'")
                status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                
            if status != 'FAILED':
                dist_km = dist_val
                if 'miles' in row_data or 'distance_miles' in row_data:
                    dist_km = dist_val * Decimal('1.60934')
                    
                # Determine ground factor
                if 'train' in transport_type or 'rail' in transport_type:
                    factor = EMISSION_FACTORS['GROUND_TRAIN']
                    category_type = 'Train'
                elif 'taxi' in transport_type:
                    factor = EMISSION_FACTORS['GROUND_TAXI']
                    category_type = 'Taxi'
                else: # Rental car
                    category_type = f"Rental Car ({fuel_type})"
                    if fuel_type == 'Electric':
                        factor = EMISSION_FACTORS['GROUND_CAR_ELECTRIC']
                    elif fuel_type == 'Hybrid':
                        factor = EMISSION_FACTORS['GROUND_CAR_HYBRID']
                    elif fuel_type == 'Diesel':
                        factor = EMISSION_FACTORS['GROUND_CAR_DIESEL']
                    else:
                        factor = EMISSION_FACTORS['GROUND_CAR_PETROL']
                        
                co2e_kg = dist_km * factor
                normalized_qty = dist_km
                normalized_unit = 'km'
                category = 'Business Travel - Ground'
                source_identifier = transport_type
                description = f"Ground Transport: {category_type}. Distance: {dist_km:.2f} km. Cost: {cost} {currency}."
                
                # Check for abnormally high distance in ground transport
                if dist_km > Decimal('1000.00'):
                    validation_errors.append(f"Suspicious ground transport distance: {dist_km:.2f} km in a single booking.")
                    status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                    
    # Ingestion record creation
    ingested_row = IngestedRow.objects.create(
        tenant=tenant,
        source_type='TRAVEL',
        raw_data=row_data,
        status=status,
        validation_errors=validation_errors,
        uploaded_by=user_name
    )
    
    # Audit Trail for Ingestion
    AuditTrail.objects.create(
        tenant=tenant,
        source_row=ingested_row,
        user=user_name,
        action='INGEST',
        previous_status=None,
        new_status=status,
        details={'validation_errors': validation_errors}
    )
    
    # Write normalized data only if not failed
    if status != 'FAILED' and activity_date:
        NormalizedData.objects.create(
            tenant=tenant,
            source_row=ingested_row,
            scope=scope,
            category=category,
            activity_date=activity_date,
            raw_quantity=safe_decimal(row_data.get('distance_km') or row_data.get('distance_miles') or row_data.get('number_of_nights') or 0),
            raw_unit=str(row_data.get('cabin_class') or row_data.get('transport_type') or row_data.get('country') or 'units'),
            normalized_quantity=normalized_qty,
            normalized_unit=normalized_unit,
            co2e_kg=co2e_kg,
            source_identifier=source_identifier,
            description=description
        )
        
    return ingested_row

def recalculate_normalized_data(ingested_row, user_name='System'):
    """
    Called when a row's raw_data is edited by an analyst.
    Removes the old normalized data (if any), re-runs validation/normalization,
    and updates the status based on new findings.
    """
    # Delete existing normalized data
    NormalizedData.objects.filter(source_row=ingested_row).delete()
    
    # Temporarily fetch raw_data and tenant
    raw = ingested_row.raw_data
    tenant = ingested_row.tenant
    source = ingested_row.source_type
    
    # We will invoke the correct validation/normalization logic without creating a new IngestedRow.
    # We will simulate the function logic and update ingested_row in place.
    validation_errors = []
    status = 'PENDING'
    activity_date = None
    normalized_qty = Decimal('0.00')
    normalized_unit = ''
    co2e_kg = Decimal('0.00')
    category = ''
    scope = ''
    source_identifier = ''
    description = ''
    
    if source == 'SAP':
        posting_date_raw = raw.get('BUDAT') or raw.get('Posting_Date') or raw.get('posting_date')
        quantity_raw = raw.get('MENGE') or raw.get('Quantity') or raw.get('quantity')
        unit_raw = raw.get('MEINS') or raw.get('Unit') or raw.get('unit')
        plant_raw = raw.get('WERKS') or raw.get('Plant') or raw.get('plant')
        amount_raw = raw.get('WRBTR') or raw.get('Amount') or raw.get('amount')
        currency_raw = raw.get('WAERS') or raw.get('Currency') or raw.get('currency') or 'EUR'
        matnr_raw = raw.get('MATNR') or raw.get('Material_Number') or raw.get('material_number')
        maktx_raw = raw.get('MAKTX') or raw.get('Material_Description') or raw.get('material_description') or ''
        
        activity_date = parse_date(posting_date_raw)
        if not activity_date:
            validation_errors.append(f"Invalid posting date format: '{posting_date_raw}'")
            status = 'FAILED'
            
        qty = safe_decimal(quantity_raw)
        if qty <= 0:
            validation_errors.append(f"Negative or zero quantity: {qty}")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
        unit = str(unit_raw).strip().upper() if unit_raw else ''
        if unit not in ['L', 'GAL', 'KG', 'LIT']:
            if unit not in ['PC', 'EA', 'ST']:
                validation_errors.append(f"Uncommon Unit of Measure: '{unit}'")
                status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                
        plant_code = str(plant_raw).strip() if plant_raw else ''
        plant_lookup = None
        if not plant_code:
            validation_errors.append("Plant code is missing")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
        else:
            plant_lookup = PlantLookup.objects.filter(tenant=tenant, plant_code=plant_code).first()
            if not plant_lookup:
                validation_errors.append(f"Unknown Plant code: '{plant_code}'")
                status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                
        cost = safe_decimal(amount_raw)
        if cost < 0:
            validation_errors.append(f"Negative cost amount: {cost}")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
        if qty > 0 and cost > 0:
            price_per_unit = cost / qty
            if "DIESEL" in maktx_raw.upper() or "HEIZOEL" in maktx_raw.upper():
                if price_per_unit < Decimal('0.40') or price_per_unit > Decimal('4.50'):
                    validation_errors.append(f"Suspicious price per unit: {price_per_unit:.2f} {currency_raw}/L")
                    status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                    
        if status != 'FAILED' and activity_date:
            maktx_upper = maktx_raw.upper()
            if 'DIESEL' in maktx_upper or 'HEIZOEL' in maktx_upper:
                category = 'Fuel - Diesel'
                scope = 'SCOPE_1'
                if unit == 'GAL':
                    normalized_qty = qty * Decimal('3.78541')
                    normalized_unit = 'L'
                else:
                    normalized_qty = qty
                    normalized_unit = 'L'
                co2e_kg = normalized_qty * EMISSION_FACTORS['FUEL_DIESEL_L']
            elif 'PETROL' in maktx_upper or 'GASOLINE' in maktx_upper or 'BENZIN' in maktx_upper:
                category = 'Fuel - Petrol'
                scope = 'SCOPE_1'
                if unit == 'GAL':
                    normalized_qty = qty * Decimal('3.78541')
                    normalized_unit = 'L'
                else:
                    normalized_qty = qty
                    normalized_unit = 'L'
                co2e_kg = normalized_qty * EMISSION_FACTORS['FUEL_PETROL_L']
            else:
                category = 'Procurement - Purchased Goods'
                scope = 'SCOPE_3'
                normalized_qty = cost
                normalized_unit = currency_raw
                co2e_kg = normalized_qty * EMISSION_FACTORS['PROCUREMENT_DEFAULT']
                
            description = f"SAP Ingest (Edited): Material {matnr_raw} ({maktx_raw}). Cost: {cost} {currency_raw}."
            if plant_lookup:
                description += f" Plant: {plant_lookup.name} ({plant_lookup.location}, {plant_lookup.country})."
                
    elif source == 'UTILITY':
        account_num = raw.get('Account_Number') or raw.get('Account Number') or raw.get('account_number')
        meter_num = raw.get('Meter_Number') or raw.get('Meter Number') or raw.get('meter_number')
        start_date_raw = raw.get('Start_Date') or raw.get('Start Date') or raw.get('start_date')
        end_date_raw = raw.get('End_Date') or raw.get('End Date') or raw.get('end_date')
        usage_raw = raw.get('Usage_kWh') or raw.get('Consumption') or raw.get('usage_kwh')
        amount_raw = raw.get('Total_Amount') or raw.get('Amount') or raw.get('amount')
        currency = raw.get('Currency') or raw.get('currency') or 'USD'
        tariff = raw.get('Tariff_Code') or raw.get('Tariff') or raw.get('tariff') or 'Standard'
        
        start_date = parse_date(start_date_raw)
        end_date = parse_date(end_date_raw)
        
        if not start_date or not end_date:
            validation_errors.append(f"Invalid billing dates: Start '{start_date_raw}', End '{end_date_raw}'")
            status = 'FAILED'
        elif start_date >= end_date:
            validation_errors.append(f"Start date ({start_date}) is after or equal to End date ({end_date})")
            status = 'FAILED'
            
        usage = safe_decimal(usage_raw)
        if usage <= 0 and status != 'FAILED':
            validation_errors.append(f"Usage is zero or negative: {usage} kWh")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
        facility = None
        meter_str = str(meter_num).strip() if meter_num else ''
        account_str = str(account_num).strip() if account_num else ''
        
        if not meter_str:
            validation_errors.append("Meter number is missing")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
        else:
            facility = FacilityLookup.objects.filter(tenant=tenant, account_number=account_str, meter_number=meter_str).first()
            if not facility:
                validation_errors.append(f"Unknown meter number '{meter_str}' under account '{account_str}'")
                status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                
        # Check overlaps (excluding current row itself)
        if start_date and end_date and meter_str:
            overlapping_rows = IngestedRow.objects.filter(
                tenant=tenant,
                source_type='UTILITY',
                status__in=['PENDING', 'APPROVED']
            ).exclude(id=ingested_row.id)
            for ov_row in overlapping_rows:
                ov_start = parse_date(ov_row.raw_data.get('Start_Date') or ov_row.raw_data.get('Start Date'))
                ov_end = parse_date(ov_row.raw_data.get('End_Date') or ov_row.raw_data.get('End Date'))
                ov_meter = ov_row.raw_data.get('Meter_Number') or ov_row.raw_data.get('Meter Number')
                
                if ov_start and ov_end and str(ov_meter).strip() == meter_str:
                    if start_date < ov_end and ov_start < end_date:
                        validation_errors.append(f"Billing period overlaps with existing row ID {ov_row.id} ({ov_start} to {ov_end})")
                        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                        break
                        
        if start_date and end_date:
            duration = (end_date - start_date).days
            if duration < 20 or duration > 40:
                validation_errors.append(f"Billing period duration of {duration} days is outside normal bounds")
                status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                
        cost = safe_decimal(amount_raw)
        if cost <= 0:
            validation_errors.append(f"Billing cost amount is negative or zero: {cost}")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
        if usage > 0 and cost > 0:
            rate_per_kwh = cost / usage
            if rate_per_kwh < Decimal('0.02') or rate_per_kwh > Decimal('0.60'):
                validation_errors.append(f"Suspicious rate: {rate_per_kwh:.3f} {currency}/kWh")
                status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                
        if status != 'FAILED' and start_date and end_date:
            duration = (end_date - start_date).days
            midpoint_delta = duration // 2
            activity_date = start_date + timedelta(days=midpoint_delta)
            
            grid_factor = facility.grid_emission_factor if facility else EMISSION_FACTORS['GRID_DEFAULT']
            co2e_kg = usage * grid_factor
            
            normalized_qty = usage
            normalized_unit = 'kWh'
            scope = 'SCOPE_2'
            category = 'Electricity'
            source_identifier = meter_str
            description = f"Utility Electricity Ingest (Edited): Account {account_str}, Meter {meter_str}. Billing: {start_date} to {end_date}. Cost: {cost} {currency}."
            if facility:
                description += f" Facility: {facility.name}."
                
    elif source == 'TRAVEL':
        booking_id = raw.get('booking_id')
        booking_type = str(raw.get('booking_type')).strip().lower() if raw.get('booking_type') else ''
        cost_raw = raw.get('cost')
        currency = raw.get('currency') or 'USD'
        
        if not booking_id:
            validation_errors.append("Travel Booking ID is missing")
            status = 'FAILED'
            
        if booking_type not in ['flight', 'hotel', 'ground']:
            validation_errors.append(f"Invalid booking type: '{booking_type}'")
            status = 'FAILED'
            
        cost = safe_decimal(cost_raw)
        if cost < 0:
            validation_errors.append(f"Negative booking cost amount: {cost}")
            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
            
        if status != 'FAILED':
            if booking_type == 'flight':
                dep_airport = str(raw.get('departure_airport', '')).strip().upper()
                arr_airport = str(raw.get('arrival_airport', '')).strip().upper()
                cabin = str(raw.get('cabin_class', 'Economy')).strip().capitalize()
                travel_date_raw = raw.get('departure_date') or raw.get('travel_date')
                
                activity_date = parse_date(travel_date_raw)
                if not activity_date:
                    validation_errors.append(f"Invalid flight date format: '{travel_date_raw}'")
                    status = 'FAILED'
                    
                if not dep_airport or not arr_airport:
                    validation_errors.append("Departure/arrival airports missing")
                    status = 'FAILED'
                    
                dist_km = Decimal('0.00')
                dist_raw = raw.get('distance_km') or raw.get('distance_miles')
                
                if not dist_raw and status != 'FAILED':
                    if dep_airport in AIRPORT_COORDINATES and arr_airport in AIRPORT_COORDINATES:
                        coord1 = AIRPORT_COORDINATES[dep_airport]
                        coord2 = AIRPORT_COORDINATES[arr_airport]
                        calculated_dist = haversine_distance(coord1[0], coord1[1], coord2[0], coord2[1])
                        dist_km = Decimal(str(calculated_dist))
                        validation_errors.append(f"Distance missing. Calculated {dep_airport}-{arr_airport} distance of {dist_km:.2f} km using Haversine fallback.")
                        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                    else:
                        validation_errors.append(f"Distance missing and airports not in coordinate lookup")
                        status = 'FAILED'
                elif dist_raw:
                    dist_val = safe_decimal(dist_raw)
                    if 'miles' in raw or 'distance_miles' in raw:
                        dist_km = dist_val * Decimal('1.60934')
                    else:
                        dist_km = dist_val
                        
                if dist_km <= 0 and status != 'FAILED':
                    validation_errors.append(f"Flight distance is negative or zero: {dist_km} km")
                    status = 'FAILED'
                    
                if status != 'FAILED':
                    is_short = dist_km < Decimal('500.00')
                    if cabin not in ['Economy', 'Premium economy', 'Business', 'First']:
                        validation_errors.append(f"Unknown flight cabin class: '{cabin}'. Defaulted to Economy.")
                        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                        cabin = 'Economy'
                        
                    if is_short:
                        factor = EMISSION_FACTORS['FLIGHT_SHORT_HAUL_BUSINESS'] if cabin in ['Business', 'First'] else EMISSION_FACTORS['FLIGHT_SHORT_HAUL_ECONOMY']
                    else:
                        factor = EMISSION_FACTORS['FLIGHT_LONG_HAUL_BUSINESS'] if cabin in ['Business', 'First'] else EMISSION_FACTORS['FLIGHT_LONG_HAUL_ECONOMY']
                        
                    co2e_kg = dist_km * factor
                    normalized_qty = dist_km
                    normalized_unit = 'km'
                    scope = 'SCOPE_3'
                    category = 'Business Travel - Flight'
                    source_identifier = f"{dep_airport}-{arr_airport}"
                    description = f"Flight (Edited): {dep_airport} to {arr_airport} ({cabin}). Distance: {dist_km:.2f} km."
                    
            elif booking_type == 'hotel':
                checkin_raw = raw.get('check_in_date')
                checkout_raw = raw.get('check_out_date')
                country = str(raw.get('country', 'US')).strip().upper()
                hotel_name = raw.get('hotel_name', 'Unknown Hotel')
                rooms = int(raw.get('number_of_rooms') or 1)
                nights_raw = raw.get('number_of_nights')
                
                activity_date = parse_date(checkin_raw)
                if not activity_date:
                    validation_errors.append(f"Invalid check-in date: '{checkin_raw}'")
                    status = 'FAILED'
                    
                checkout_date = parse_date(checkout_raw)
                nights = 0
                if activity_date and checkout_date:
                    nights = (checkout_date - activity_date).days
                elif nights_raw:
                    nights = int(nights_raw)
                    
                if nights <= 0 and status != 'FAILED':
                    validation_errors.append("Invalid nights")
                    status = 'FAILED'
                    
                if rooms <= 0 and status != 'FAILED':
                    validation_errors.append("Invalid rooms")
                    status = 'FAILED'
                    
                if status != 'FAILED':
                    factor = EMISSION_FACTORS.get(f"HOTEL_{country}", EMISSION_FACTORS['HOTEL_DEFAULT'])
                    room_nights = Decimal(str(nights * rooms))
                    co2e_kg = room_nights * factor
                    normalized_qty = room_nights
                    normalized_unit = 'room-nights'
                    scope = 'SCOPE_3'
                    category = 'Business Travel - Hotel'
                    source_identifier = country
                    description = f"Hotel Night (Edited): {hotel_name} in {country}. Rooms: {rooms}, Nights: {nights}."
                    
                    if cost > 0 and room_nights > 0:
                        cost_per_night = cost / room_nights
                        if cost_per_night < Decimal('10.00') or cost_per_night > Decimal('1000.00'):
                            validation_errors.append(f"Suspicious hotel rate: {cost_per_night:.2f} {currency}/night")
                            status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                            
            elif booking_type == 'ground':
                transport_type = str(raw.get('transport_type')).strip().lower() if raw.get('transport_type') else ''
                fuel_type = str(raw.get('fuel_type', 'Petrol')).strip().capitalize()
                travel_date_raw = raw.get('travel_date') or raw.get('departure_date')
                dist_raw = raw.get('distance_km') or raw.get('distance_miles')
                
                activity_date = parse_date(travel_date_raw)
                if not activity_date:
                    validation_errors.append(f"Invalid travel date: '{travel_date_raw}'")
                    status = 'FAILED'
                    
                dist_val = safe_decimal(dist_raw)
                if dist_val <= 0 and status != 'FAILED':
                    validation_errors.append(f"Ground travel distance: {dist_val}")
                    status = 'FAILED'
                    
                if transport_type not in ['rental car', 'rental_car', 'car rental', 'car_rental', 'taxi', 'train', 'rail']:
                    validation_errors.append(f"Uncommon transport type: '{transport_type}'")
                    status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'
                    
                if status != 'FAILED':
                    dist_km = dist_val
                    if 'miles' in raw or 'distance_miles' in raw:
                        dist_km = dist_val * Decimal('1.60934')
                        
                    if 'train' in transport_type or 'rail' in transport_type:
                        factor = EMISSION_FACTORS['GROUND_TRAIN']
                        category_type = 'Train'
                    elif 'taxi' in transport_type:
                        factor = EMISSION_FACTORS['GROUND_TAXI']
                        category_type = 'Taxi'
                    else:
                        category_type = f"Rental Car ({fuel_type})"
                        if fuel_type == 'Electric':
                            factor = EMISSION_FACTORS['GROUND_CAR_ELECTRIC']
                        elif fuel_type == 'Hybrid':
                            factor = EMISSION_FACTORS['GROUND_CAR_HYBRID']
                        elif fuel_type == 'Diesel':
                            factor = EMISSION_FACTORS['GROUND_CAR_DIESEL']
                        else:
                            factor = EMISSION_FACTORS['GROUND_CAR_PETROL']
                            
                    co2e_kg = dist_km * factor
                    normalized_qty = dist_km
                    normalized_unit = 'km'
                    scope = 'SCOPE_3'
                    category = 'Business Travel - Ground'
                    source_identifier = transport_type
                    description = f"Ground Transport (Edited): {category_type}. Distance: {dist_km:.2f} km."
                    
                    if dist_km > Decimal('1000.00'):
                        validation_errors.append(f"Suspicious ground transport distance: {dist_km:.2f} km")
                        status = 'SUSPICIOUS' if status != 'FAILED' else 'FAILED'

    # Save validation errors and updated status to ingested_row
    ingested_row.validation_errors = validation_errors
    # Do not set status to PENDING if it was already APPROVED before editing,
    # unless we want to reset it. Let's reset it to SUSPICIOUS or PENDING based on the recalculation.
    # Actually, in the audit logic, an analyst edit resets status to PENDING or SUSPICIOUS.
    ingested_row.status = status
    ingested_row.save()
    
    # Save the new normalized record if not failed
    if status != 'FAILED' and activity_date:
        NormalizedData.objects.create(
            tenant=tenant,
            source_row=ingested_row,
            scope=scope,
            category=category,
            activity_date=activity_date,
            raw_quantity=qty if source == 'SAP' else usage if source == 'UTILITY' else safe_decimal(raw.get('distance_km') or raw.get('distance_miles') or raw.get('number_of_nights') or 0),
            raw_unit=unit if source == 'SAP' else 'kWh' if source == 'UTILITY' else str(raw.get('cabin_class') or raw.get('transport_type') or raw.get('country') or 'units'),
            normalized_quantity=normalized_qty,
            normalized_unit=normalized_unit,
            co2e_kg=co2e_kg,
            source_identifier=source_identifier,
            description=description
        )
        
    return ingested_row
