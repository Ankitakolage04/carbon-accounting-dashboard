import csv
import io
from decimal import Decimal
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Tenant, IngestedRow, NormalizedData, AuditTrail, PlantLookup, FacilityLookup
from .parsers import process_sap_row, process_utility_row, process_travel_row, recalculate_normalized_data
class ApiIndexView(APIView):
    def get(self, request):
        return Response({
            'message': 'Welcome to Aethera Carbon Ledger API',
            'endpoints': {
                'tenants': '/api/v1/tenants/',
                'setup-lookups': '/api/v1/setup-lookups/',
                'ingest': '/api/v1/ingest/',
                'ingested-rows': '/api/v1/ingested-rows/',
                'ingested-rows-detail': '/api/v1/ingested-rows/<pk>/',
                'approve-row': '/api/v1/ingested-rows/<pk>/approve/',
                'edit-row': '/api/v1/ingested-rows/<pk>/edit/',
                'analytics': '/api/v1/analytics/'
            }
        }, status=status.HTTP_200_OK)

class TenantListCreateView(APIView):
    def get(self, request):
        tenants = Tenant.objects.all().values('id', 'name', 'api_key', 'created_at')
        return Response(list(tenants), status=status.HTTP_200_OK)

    def post(self, request):
        name = request.data.get('name')
        if not name:
            return Response({'error': 'Name is required'}, status=status.HTTP_400_BAD_REQUEST)
        tenant = Tenant.objects.create(name=name)
        return Response({
            'id': str(tenant.id),
            'name': tenant.name,
            'api_key': tenant.api_key
        }, status=status.HTTP_201_CREATED)

class SetupLookupsView(APIView):
    """Developer helper to prepopulate standard plants and facilities for testing."""
    def post(self, request):
        tenant_id = request.data.get('tenant_id')
        tenant = get_object_or_404(Tenant, id=tenant_id)
        
        # 1. Plants
        plants = [
            {'plant_code': 'DE01', 'name': 'Berlin Assembly', 'location': 'Berlin', 'country': 'DE', 'grid_emission_factor': Decimal('0.35')},
            {'plant_code': 'US01', 'name': 'Austin Gigafactory', 'location': 'Austin, TX', 'country': 'US', 'grid_emission_factor': Decimal('0.25')},
            {'plant_code': 'IN01', 'name': 'Mumbai Logistics', 'location': 'Mumbai', 'country': 'IN', 'grid_emission_factor': Decimal('0.75')},
        ]
        created_plants = []
        for p in plants:
            obj, created = PlantLookup.objects.get_or_create(
                tenant=tenant,
                plant_code=p['plant_code'],
                defaults={
                    'name': p['name'],
                    'location': p['location'],
                    'country': p['country'],
                    'grid_emission_factor': p['grid_emission_factor']
                }
            )
            created_plants.append({'plant_code': obj.plant_code, 'created': created})
            
        # 2. Facilities
        facilities = [
            {'account_number': 'ACC-9988', 'meter_number': 'MET-1122', 'name': 'NY HQ Facility', 'location': 'New York, NY', 'country': 'US', 'grid_emission_factor': Decimal('0.28')},
            {'account_number': 'ACC-4455', 'meter_number': 'MET-5566', 'name': 'Frankfurt Data Center', 'location': 'Frankfurt', 'country': 'DE', 'grid_emission_factor': Decimal('0.35')},
            {'account_number': 'ACC-1122', 'meter_number': 'MET-9988', 'name': 'Bangalore Office', 'location': 'Bangalore', 'country': 'IN', 'grid_emission_factor': Decimal('0.72')},
        ]
        created_facilities = []
        for f in facilities:
            obj, created = FacilityLookup.objects.get_or_create(
                tenant=tenant,
                account_number=f['account_number'],
                meter_number=f['meter_number'],
                defaults={
                    'name': f['name'],
                    'location': f['location'],
                    'country': f['country'],
                    'grid_emission_factor': f['grid_emission_factor']
                }
            )
            created_facilities.append({'account_meter': f"{obj.account_number}/{obj.meter_number}", 'created': created})
            
        return Response({
            'message': 'Lookup data populated successfully',
            'plants': created_plants,
            'facilities': created_facilities
        }, status=status.HTTP_200_OK)

class IngestDataView(APIView):
    """
    Ingests data from three different sources: SAP, UTILITY, or TRAVEL.
    Supports file uploads (for SAP/UTILITY CSVs) and JSON payloads.
    """
    def post(self, request):
        tenant_id = request.data.get('tenant_id')
        source_type = request.data.get('source_type')
        user_name = request.data.get('user_name', 'System / API')
        
        if not tenant_id or not source_type:
            return Response({'error': 'tenant_id and source_type are required'}, status=status.HTTP_400_BAD_REQUEST)
            
        tenant = get_object_or_404(Tenant, id=tenant_id)
        source_type = source_type.upper()
        
        if source_type not in ['SAP', 'UTILITY', 'TRAVEL']:
            return Response({'error': 'Invalid source_type. Must be SAP, UTILITY, or TRAVEL'}, status=status.HTTP_400_BAD_REQUEST)
            
        # File Upload vs JSON Parsing
        csv_file = request.FILES.get('file')
        results = []
        
        if csv_file:
            # Parse CSV
            try:
                decoded_file = csv_file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)
                
                for row in reader:
                    # Clean empty spaces in keys and values
                    cleaned_row = {k.strip(): v.strip() for k, v in row.items() if k is not None}
                    
                    if source_type == 'SAP':
                        ingested = process_sap_row(cleaned_row, tenant, user_name)
                    elif source_type == 'UTILITY':
                        ingested = process_utility_row(cleaned_row, tenant, user_name)
                    else:
                        return Response({'error': 'TRAVEL source type does not support CSV uploads'}, status=status.HTTP_400_BAD_REQUEST)
                        
                    results.append({
                        'id': ingested.id,
                        'status': ingested.status,
                        'validation_errors': ingested.validation_errors
                    })
            except Exception as e:
                return Response({'error': f'Failed to process CSV file: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
                
        else:
            # Parse JSON body
            payload = request.data.get('data')
            if not payload:
                return Response({'error': 'No data payload found in request'}, status=status.HTTP_400_BAD_REQUEST)
                
            # If payload is a single object, wrap it in a list
            if not isinstance(payload, list):
                payload = [payload]
                
            for record in payload:
                if source_type == 'SAP':
                    ingested = process_sap_row(record, tenant, user_name)
                elif source_type == 'UTILITY':
                    ingested = process_utility_row(record, tenant, user_name)
                else:  # TRAVEL
                    ingested = process_travel_row(record, tenant, user_name)
                    
                results.append({
                    'id': ingested.id,
                    'status': ingested.status,
                    'validation_errors': ingested.validation_errors
                })
                
        return Response({
            'message': f'Ingested {len(results)} rows successfully',
            'rows': results
        }, status=status.HTTP_201_CREATED)

class IngestedRowListView(APIView):
    def get(self, request):
        tenant_id = request.query_params.get('tenant_id')
        status_filter = request.query_params.get('status')
        source_filter = request.query_params.get('source_type')
        
        query = IngestedRow.objects.all()
        if tenant_id:
            query = query.filter(tenant_id=tenant_id)
        if status_filter:
            query = query.filter(status=status_filter)
        if source_filter:
            query = query.filter(source_type=source_filter)
            
        # Serialize fields manually to return clean details
        rows = []
        for r in query.order_by('-created_at'):
            normalized = getattr(r, 'normalized_record', None)
            co2e_val = float(normalized.co2e_kg) if normalized else None
            scope_val = normalized.scope if normalized else None
            cat_val = normalized.category if normalized else None
            activity_date_val = str(normalized.activity_date) if normalized else None
            
            rows.append({
                'id': r.id,
                'source_type': r.source_type,
                'raw_data': r.raw_data,
                'status': r.status,
                'validation_errors': r.validation_errors,
                'uploaded_by': r.uploaded_by,
                'created_at': r.created_at.isoformat(),
                'updated_at': r.updated_at.isoformat(),
                'emissions_co2e_kg': co2e_val,
                'scope': scope_val,
                'category': cat_val,
                'activity_date': activity_date_val
            })
            
        return Response(rows, status=status.HTTP_200_OK)

class IngestedRowDetailView(APIView):
    def get(self, request, pk):
        row = get_object_or_404(IngestedRow, id=pk)
        normalized = getattr(row, 'normalized_record', None)
        audits = row.audit_records.all().order_by('-timestamp')
        
        audit_list = [{
            'user': a.user,
            'action': a.action,
            'previous_status': a.previous_status,
            'new_status': a.new_status,
            'details': a.details,
            'timestamp': a.timestamp.isoformat()
        } for a in audits]
        
        normalized_data = None
        if normalized:
            normalized_data = {
                'scope': normalized.scope,
                'category': normalized.category,
                'activity_date': str(normalized.activity_date),
                'raw_quantity': float(normalized.raw_quantity),
                'raw_unit': normalized.raw_unit,
                'normalized_quantity': float(normalized.normalized_quantity),
                'normalized_unit': normalized.normalized_unit,
                'co2e_kg': float(normalized.co2e_kg),
                'source_identifier': normalized.source_identifier,
                'description': normalized.description
            }
            
        return Response({
            'id': row.id,
            'tenant_id': str(row.tenant.id),
            'source_type': row.source_type,
            'raw_data': row.raw_data,
            'status': row.status,
            'validation_errors': row.validation_errors,
            'uploaded_by': row.uploaded_by,
            'created_at': row.created_at.isoformat(),
            'updated_at': row.updated_at.isoformat(),
            'normalized_data': normalized_data,
            'audit_trail': audit_list
        }, status=status.HTTP_200_OK)

class ApproveRowView(APIView):
    def post(self, request, pk):
        row = get_object_or_404(IngestedRow, id=pk)
        user_name = request.data.get('user_name', 'Analyst')
        
        if row.status == 'APPROVED':
            return Response({'error': 'Row is already approved and locked for auditing'}, status=status.HTTP_400_BAD_REQUEST)
            
        if row.status == 'FAILED':
            return Response({'error': 'Cannot approve a failed ingestion row. Correct raw errors first.'}, status=status.HTTP_400_BAD_REQUEST)
            
        previous_status = row.status
        row.status = 'APPROVED'
        row.save()
        
        # Log Audit
        AuditTrail.objects.create(
            tenant=row.tenant,
            source_row=row,
            user=user_name,
            action='APPROVE',
            previous_status=previous_status,
            new_status='APPROVED',
            details={'message': 'Row approved and locked for auditing.'}
        )
        
        return Response({
            'message': f'Row {row.id} approved successfully and locked.',
            'status': row.status
        }, status=status.HTTP_200_OK)

class EditRowView(APIView):
    def post(self, request, pk):
        row = get_object_or_404(IngestedRow, id=pk)
        user_name = request.data.get('user_name', 'Analyst')
        new_raw_data = request.data.get('raw_data')
        
        if row.status == 'APPROVED':
            return Response({'error': 'Row is approved and locked. Modifications are disabled.'}, status=status.HTTP_400_BAD_REQUEST)
            
        if not new_raw_data:
            return Response({'error': 'New raw_data is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        previous_status = row.status
        previous_raw_data = row.raw_data
        
        # Update raw data
        row.raw_data = new_raw_data
        row.save()
        
        # Re-run parser logic (recalculates normalized record and updates status)
        recalculate_normalized_data(row, user_name)
        
        # Log Audit
        AuditTrail.objects.create(
            tenant=row.tenant,
            source_row=row,
            user=user_name,
            action='EDIT',
            previous_status=previous_status,
            new_status=row.status,
            details={
                'previous_raw_data': previous_raw_data,
                'new_raw_data': row.raw_data,
                'validation_errors': row.validation_errors
            }
        )
        
        return Response({
            'message': f'Row {row.id} updated and re-validated successfully.',
            'status': row.status,
            'validation_errors': row.validation_errors
        }, status=status.HTTP_200_OK)

class AnalyticsSummaryView(APIView):
    def get(self, request):
        tenant_id = request.query_params.get('tenant_id')
        if not tenant_id:
            return Response({'error': 'tenant_id query param is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        tenant = get_object_or_404(Tenant, id=tenant_id)
        
        # Only aggregate APPROVED rows for official reporting (or show both approved/pending if requested).
        # We will filter on NormalizedData where source_row.status == 'APPROVED' for official numbers,
        # and show draft totals separately to wow the PM!
        base_approved = NormalizedData.objects.filter(tenant=tenant, source_row__status='APPROVED')
        base_all = NormalizedData.objects.filter(tenant=tenant)
        
        # 1. Totals
        approved_co2e_kg = base_approved.aggregate(total=Sum('co2e_kg'))['total'] or Decimal('0.00')
        all_co2e_kg = base_all.aggregate(total=Sum('co2e_kg'))['total'] or Decimal('0.00')
        
        # 2. Scope breakdown
        scopes_approved = base_approved.values('scope').annotate(total=Sum('co2e_kg'))
        scopes_all = base_all.values('scope').annotate(total=Sum('co2e_kg'))
        
        scope_approved_map = {item['scope']: float(item['total']) for item in scopes_approved}
        scope_all_map = {item['scope']: float(item['total']) for item in scopes_all}
        
        for sc in ['SCOPE_1', 'SCOPE_2', 'SCOPE_3']:
            scope_approved_map.setdefault(sc, 0.0)
            scope_all_map.setdefault(sc, 0.0)
            
        # 3. Category breakdown
        categories_all = base_all.values('category').annotate(total=Sum('co2e_kg')).order_by('-total')
        category_breakdown = [{
            'category': item['category'],
            'co2e_kg': float(item['total'])
        } for item in categories_all]
        
        # 4. Status counts
        counts = IngestedRow.objects.filter(tenant=tenant).values('status').annotate(count=Count('id'))
        count_map = {item['status']: item['count'] for item in counts}
        for st in ['PENDING', 'APPROVED', 'FAILED', 'SUSPICIOUS']:
            count_map.setdefault(st, 0)
            
        # 5. Monthly trend
        monthly_trend = base_all.annotate(
            month=TruncMonth('activity_date')
        ).values('month').annotate(
            total=Sum('co2e_kg')
        ).order_by('month')
        
        trend = [{
            'month': item['month'].strftime('%Y-%m') if item['month'] else 'Unknown',
            'co2e_kg': float(item['total'])
        } for item in monthly_trend]
        
        return Response({
            'official_approved_emissions_mt': float(approved_co2e_kg) / 1000.0, # convert kg to Metric Tons
            'draft_all_emissions_mt': float(all_co2e_kg) / 1000.0,
            'scopes_approved': scope_approved_map,
            'scopes_all': scope_all_map,
            'category_breakdown': category_breakdown,
            'status_counts': count_map,
            'monthly_trend': trend
        }, status=status.HTTP_200_OK)
