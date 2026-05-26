from django.urls import path
from .views import (
    ApiIndexView, TenantListCreateView, SetupLookupsView, IngestDataView,
    IngestedRowListView, IngestedRowDetailView, ApproveRowView,
    EditRowView, AnalyticsSummaryView
)

urlpatterns = [
    path('', ApiIndexView.as_view(), name='api-index'),
    path('tenants/', TenantListCreateView.as_view(), name='tenant-list-create'),
    path('setup-lookups/', SetupLookupsView.as_view(), name='setup-lookups'),
    path('ingest/', IngestDataView.as_view(), name='ingest-data'),
    path('ingested-rows/', IngestedRowListView.as_view(), name='ingested-row-list'),
    path('ingested-rows/<int:pk>/', IngestedRowDetailView.as_view(), name='ingested-row-detail'),
    path('ingested-rows/<int:pk>/approve/', ApproveRowView.as_view(), name='approve-row'),
    path('ingested-rows/<int:pk>/edit/', EditRowView.as_view(), name='edit-row'),
    path('analytics/', AnalyticsSummaryView.as_view(), name='analytics-summary'),
]
