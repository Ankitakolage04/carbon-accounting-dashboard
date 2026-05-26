import React, { useState, useEffect } from 'react';
import { 
  Upload, RefreshCw, CheckCircle, AlertTriangle, AlertOctagon, 
  FileText, ArrowRight, ShieldCheck, Database, Layers, Check, 
  Plus, Code, Download, X, Eye, Edit3, Trash2
} from 'lucide-react';

const API_BASE = 'http://localhost:8000/api/v1';

const DEFAULT_TRAVEL_JSON = `[
  {
    "booking_id": "TRV-FL-8899",
    "employee_id": "EMP-234",
    "booking_type": "flight",
    "departure_airport": "JFK",
    "arrival_airport": "LHR",
    "cabin_class": "Business",
    "departure_date": "2026-05-18",
    "cost": 1450.00,
    "currency": "USD"
  },
  {
    "booking_id": "TRV-HT-4455",
    "employee_id": "EMP-102",
    "booking_type": "hotel",
    "check_in_date": "2026-05-18",
    "check_out_date": "2026-05-22",
    "hotel_name": "Radisson Blu Munich",
    "city": "Munich",
    "country": "DE",
    "number_of_rooms": 1,
    "cost": 640.00,
    "currency": "EUR"
  },
  {
    "booking_id": "TRV-GR-1122",
    "employee_id": "EMP-102",
    "booking_type": "ground",
    "transport_type": "rental_car",
    "fuel_type": "Electric",
    "distance_km": 350.00,
    "travel_date": "2026-05-19",
    "cost": 120.00,
    "currency": "EUR"
  },
  {
    "booking_id": "TRV-FL-BAD",
    "employee_id": "EMP-999",
    "booking_type": "flight",
    "departure_airport": "JFK",
    "arrival_airport": "XYZ",
    "cabin_class": "Economy",
    "departure_date": "2026-05-20",
    "cost": 500.00,
    "currency": "USD"
  }
]`;

export default function App() {
  const [tenants, setTenants] = useState([]);
  const [activeTenantId, setActiveTenantId] = useState('');
  const [newTenantName, setNewTenantName] = useState('');
  const [showCreateTenant, setShowCreateTenant] = useState(false);
  
  // Dashboard & Table States
  const [rows, setRows] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [selectedStatusTab, setSelectedStatusTab] = useState('PENDING');
  const [selectedSourceFilter, setSelectedSourceFilter] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(false);

  // Ingestion State
  const [ingestionTab, setIngestionTab] = useState('sap'); // sap | utility | travel
  const [travelPayload, setTravelPayload] = useState(DEFAULT_TRAVEL_JSON);
  const [uploadStatus, setUploadStatus] = useState({ type: '', message: '' });

  // Detail Modal State
  const [selectedRow, setSelectedRow] = useState(null);
  const [detailedRowData, setDetailedRowData] = useState(null);
  const [isEditMode, setIsEditMode] = useState(false);
  const [editableJson, setEditableJson] = useState('');
  const [modalError, setModalError] = useState('');

  // Initial load
  useEffect(() => {
    fetchTenants();
  }, []);

  // Fetch rows & analytics whenever tenant changes or table is refreshed
  useEffect(() => {
    if (activeTenantId) {
      fetchDashboardData();
    }
  }, [activeTenantId, refreshKey, selectedStatusTab, selectedSourceFilter]);

  const fetchTenants = async () => {
    try {
      const res = await fetch(`${API_BASE}/tenants/`);
      if (res.ok) {
        const data = await res.json();
        setTenants(data);
        if (data.length > 0 && !activeTenantId) {
          setActiveTenantId(data[0].id);
        }
      }
    } catch (e) {
      console.error("Error fetching tenants:", e);
    }
  };

  const createTenant = async (e) => {
    e.preventDefault();
    if (!newTenantName.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/tenants/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newTenantName })
      });
      if (res.ok) {
        const data = await res.json();
        setTenants([...tenants, data]);
        setActiveTenantId(data.id);
        setNewTenantName('');
        setShowCreateTenant(false);
        // Pre-populate lookup tables for standard testing
        await fetch(`${API_BASE}/setup-lookups/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: data.id })
        });
        setRefreshKey(prev => prev + 1);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const runSetupLookups = async () => {
    if (!activeTenantId) return;
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/setup-lookups/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: activeTenantId })
      });
      if (res.ok) {
        alert("Facility & Plant master lookup tables configured successfully!");
        setRefreshKey(prev => prev + 1);
      }
    } catch (err) {
      alert("Failed to pre-populate maps.");
    } finally {
      setLoading(false);
    }
  };

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      // 1. Fetch Ingested Rows (filtered by status)
      let url = `${API_BASE}/ingested-rows/?tenant_id=${activeTenantId}`;
      if (selectedStatusTab) {
        url += `&status=${selectedStatusTab}`;
      }
      if (selectedSourceFilter) {
        url += `&source_type=${selectedSourceFilter}`;
      }
      const resRows = await fetch(url);
      if (resRows.ok) {
        const rowList = await resRows.json();
        setRows(rowList);
      }

      // 2. Fetch Analytics
      const resAnalytics = await fetch(`${API_BASE}/analytics/?tenant_id=${activeTenantId}`);
      if (resAnalytics.ok) {
        const analData = await resAnalytics.json();
        setAnalytics(analData);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // CSV Sample Downloads
  const downloadSampleSAP = () => {
    const csvContent = "BUDAT,MENGE,MEINS,WERKS,WRBTR,WAERS,MATNR,MAKTX\n" +
      "2026-05-10,1200,L,DE01,1800,EUR,MAT-FUEL-01,Diesel fuel procurement\n" +
      "2026-05-11,250,GAL,US01,950,USD,MAT-FUEL-02,Petrol fuel procurement\n" +
      "2026-05-12,50,PC,DE01,150,EUR,MAT-PROC-99,Standard office supplies (Scope 3)\n" +
      "2026-05-13,600,L,DE99,900,EUR,MAT-FUEL-01,Diesel (Suspicious: unknown plant DE99)\n" +
      "2026-05-14,20,L,DE01,240,EUR,MAT-FUEL-01,Diesel (Suspicious: high rate 12.00/L)";
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", "sap_emission_sample.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const downloadSampleUtility = () => {
    const csvContent = "Account_Number,Meter_Number,Start_Date,End_Date,Usage_kWh,Total_Amount,Currency,Tariff_Code\n" +
      "ACC-9988,MET-1122,2026-04-01,2026-05-01,15000,4200,USD,TOU-8\n" +
      "ACC-4455,MET-5566,2026-04-01,2026-05-01,28000,9800,EUR,STANDARD\n" +
      "ACC-9988,MET-1122,2026-04-15,2026-05-15,8000,2440,USD,TOU-8 (Suspicious: overlaps ACC-9988/MET-1122)\n" +
      "ACC-9988,MET-1122,2026-05-01,2026-05-05,500,120,USD,TOU-8 (Suspicious: short 4-day cycle)";
      
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", "utility_emission_sample.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Upload/Ingest handler
  const handleFileUpload = async (e, type) => {
    const file = e.target.files[0];
    if (!file) return;

    setUploadStatus({ type: 'loading', message: `Uploading ${file.name}...` });
    const formData = new FormData();
    formData.append('tenant_id', activeTenantId);
    formData.append('source_type', type);
    formData.append('file', file);
    formData.append('user_name', 'Analyst Upload');

    try {
      const res = await fetch(`${API_BASE}/ingest/`, {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        setUploadStatus({ type: 'success', message: `Successfully ingested ${data.rows.length} rows!` });
        setRefreshKey(prev => prev + 1);
      } else {
        setUploadStatus({ type: 'error', message: data.error || 'Ingestion failed.' });
      }
    } catch (err) {
      setUploadStatus({ type: 'error', message: 'Failed to communicate with API.' });
    }
  };

  const handleTravelTrigger = async () => {
    setUploadStatus({ type: 'loading', message: 'Sending travel payload webhook...' });
    try {
      let parsed;
      try {
        parsed = JSON.parse(travelPayload);
      } catch (err) {
        setUploadStatus({ type: 'error', message: 'Invalid JSON syntax.' });
        return;
      }

      const res = await fetch(`${API_BASE}/ingest/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: activeTenantId,
          source_type: 'TRAVEL',
          data: parsed,
          user_name: 'Concur Webhook'
        })
      });
      const data = await res.json();
      if (res.ok) {
        setUploadStatus({ 
          type: 'success', 
          message: `Webhook simulated! Ingested ${data.rows.length} travel items successfully.` 
        });
        setRefreshKey(prev => prev + 1);
      } else {
        setUploadStatus({ type: 'error', message: data.error || 'Webhook call failed.' });
      }
    } catch (err) {
      setUploadStatus({ type: 'error', message: 'API connection failed.' });
    }
  };

  // Open Details Modal/Drawer
  const openRowDetails = async (row) => {
    setSelectedRow(row);
    setModalError('');
    setIsEditMode(false);
    try {
      const res = await fetch(`${API_BASE}/ingested-rows/${row.id}/`);
      if (res.ok) {
        const details = await res.json();
        setDetailedRowData(details);
        setEditableJson(JSON.stringify(details.raw_data, null, 2));
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Approve Row Action
  const approveRow = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/ingested-rows/${id}/approve/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_name: 'Analyst Override' })
      });
      const data = await res.json();
      if (res.ok) {
        // Refresh details modal & dashboard
        openRowDetails(selectedRow);
        setRefreshKey(prev => prev + 1);
      } else {
        setModalError(data.error);
      }
    } catch (err) {
      setModalError("Communication error approving row.");
    }
  };

  // Save Edit Row Action
  const saveRowEdit = async () => {
    setModalError('');
    let parsedFields;
    try {
      parsedFields = JSON.parse(editableJson);
    } catch (err) {
      setModalError("Invalid JSON format. Check fields syntax.");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/ingested-rows/${selectedRow.id}/edit/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          raw_data: parsedFields,
          user_name: 'Analyst Manual Correction'
        })
      });
      const data = await res.json();
      if (res.ok) {
        setIsEditMode(false);
        openRowDetails(selectedRow);
        setRefreshKey(prev => prev + 1);
      } else {
        setModalError(data.error);
      }
    } catch (err) {
      setModalError("Failed to update record on server.");
    }
  };

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="brand">
          <div>
            <div className="brand-logo">AETHERA</div>
            <div className="brand-tagline">Carbon Ledger Ingestion Console</div>
          </div>
        </div>

        <div className="tenant-selector">
          <Database size={16} className="text-muted" />
          <select 
            className="select-input"
            value={activeTenantId} 
            onChange={(e) => setActiveTenantId(e.target.value)}
          >
            {tenants.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>

          <button className="btn btn-secondary" onClick={() => setShowCreateTenant(true)}>
            <Plus size={16} /> Tenant
          </button>
          
          <button className="btn btn-secondary" onClick={runSetupLookups}>
            <RefreshCw size={14} /> Master Maps
          </button>
        </div>
      </header>

      {/* Show Create Tenant Form Modal */}
      {showCreateTenant && (
        <div className="modal-overlay" style={{ justifyContent: 'center', alignItems: 'center' }}>
          <div className="glass" style={{ padding: 32, width: 400, position: 'relative' }}>
            <button className="modal-close" style={{ position: 'absolute', right: 16, top: 16 }} onClick={() => setShowCreateTenant(false)}>
              <X size={20} />
            </button>
            <h3 style={{ marginBottom: 16 }}>Register New Tenant</h3>
            <form onSubmit={createTenant}>
              <div className="form-group">
                <label className="form-label">Company / Tenant Name</label>
                <input 
                  type="text" 
                  className="form-control" 
                  placeholder="e.g. Acme Corp" 
                  value={newTenantName}
                  onChange={(e) => setNewTenantName(e.target.value)}
                  autoFocus
                />
              </div>
              <button className="btn btn-primary" style={{ width: '100%' }}>Create & Configure Tenant</button>
            </form>
          </div>
        </div>
      )}

      {/* Metric Cards Summary */}
      <section className="dashboard-grid">
        <div className="glass metric-card" style={{ borderLeft: '4px solid var(--accent-primary)' }}>
          <div>
            <div className="metric-title">Approved Emissions</div>
            <div className="metric-value">
              {analytics ? `${analytics.official_approved_emissions_mt.toFixed(2)}` : '0.00'}
              <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 6 }}>MT CO2e</span>
            </div>
          </div>
          <div className="metric-footer">Official locked audit registry</div>
        </div>

        <div className="glass metric-card" style={{ borderLeft: '4px solid var(--accent-blue)' }}>
          <div>
            <div className="metric-title">Draft & Pending Emissions</div>
            <div className="metric-value">
              {analytics ? `${analytics.draft_all_emissions_mt.toFixed(2)}` : '0.00'}
              <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 6 }}>MT CO2e</span>
            </div>
          </div>
          <div className="metric-footer">Includes all pending & flag state rows</div>
        </div>

        <div className="glass metric-card" style={{ borderLeft: '4px solid var(--color-suspicious)' }}>
          <div>
            <div className="metric-title">Quality Flag Rate</div>
            <div className="metric-value">
              {analytics ? (
                (() => {
                  const total = analytics.status_counts.APPROVED + analytics.status_counts.PENDING + analytics.status_counts.SUSPICIOUS + analytics.status_counts.FAILED;
                  const flags = analytics.status_counts.SUSPICIOUS + analytics.status_counts.FAILED;
                  return total > 0 ? `${((flags / total) * 100).toFixed(1)}%` : '0.0%';
                })()
              ) : '0.0%'}
            </div>
          </div>
          <div className="metric-footer">Ratio of suspicious/failed to total records</div>
        </div>

        <div className="glass metric-card">
          <div>
            <div className="metric-title">Records Status Log</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, fontSize: 12 }}>
              <div style={{ color: 'var(--color-approved)' }}>
                ● Approved: {analytics?.status_counts.APPROVED || 0}
              </div>
              <div style={{ color: 'var(--color-pending)' }}>
                ● Pending: {analytics?.status_counts.PENDING || 0}
              </div>
              <div style={{ color: 'var(--color-suspicious)' }}>
                ● Suspicious: {analytics?.status_counts.SUSPICIOUS || 0}
              </div>
              <div style={{ color: 'var(--color-failed)' }}>
                ● Failed: {analytics?.status_counts.FAILED || 0}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Main Body Columns */}
      <div className="section-layout">
        {/* Ingestion Panel Side */}
        <aside className="glass control-panel">
          <h3>Data Ingestion Console</h3>
          
          <div className="tab-buttons">
            <button 
              className={`tab-btn ${ingestionTab === 'sap' ? 'active' : ''}`}
              onClick={() => setIngestionTab('sap')}
            >
              SAP MM
            </button>
            <button 
              className={`tab-btn ${ingestionTab === 'utility' ? 'active' : ''}`}
              onClick={() => setIngestionTab('utility')}
            >
              Utility Bill
            </button>
            <button 
              className={`tab-btn ${ingestionTab === 'travel' ? 'active' : ''}`}
              onClick={() => setIngestionTab('travel')}
            >
              Travel API
            </button>
          </div>

          {/* SAP CSV Tab */}
          {ingestionTab === 'sap' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Ingest flat raw SAP csv outputs. Normalizes German columns (BUDAT, MENGE, WERKS, etc.) to evaluate Scope 1 & 3 carbon output.
              </p>
              
              <button className="btn btn-secondary" onClick={downloadSampleSAP}>
                <Download size={14} /> Download Sample SAP CSV
              </button>

              <div className="dropzone">
                <Upload className="dropzone-icon" />
                <div className="dropzone-label">Upload SAP CSV File</div>
                <div className="dropzone-sub">Click to select CSV for import</div>
                <input 
                  type="file" 
                  accept=".csv" 
                  style={{ display: 'none' }} 
                  id="sap-upload"
                  onChange={(e) => handleFileUpload(e, 'SAP')}
                />
                <label htmlFor="sap-upload" className="btn btn-secondary" style={{ marginTop: 12, cursor: 'pointer' }}>
                  Choose File
                </label>
              </div>
            </div>
          )}

          {/* Utility Bill CSV Tab */}
          {ingestionTab === 'utility' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Import utility billing statements. Normalizes billing dates, flags overlaps, and resolves electricity factors for Scope 2 tracking.
              </p>

              <button className="btn btn-secondary" onClick={downloadSampleUtility}>
                <Download size={14} /> Download Sample Utility CSV
              </button>

              <div className="dropzone">
                <Upload className="dropzone-icon" />
                <div className="dropzone-label">Upload Utility CSV File</div>
                <div className="dropzone-sub">Click to select CSV for import</div>
                <input 
                  type="file" 
                  accept=".csv" 
                  style={{ display: 'none' }} 
                  id="util-upload"
                  onChange={(e) => handleFileUpload(e, 'UTILITY')}
                />
                <label htmlFor="util-upload" className="btn btn-secondary" style={{ marginTop: 12, cursor: 'pointer' }}>
                  Choose File
                </label>
              </div>
            </div>
          )}

          {/* Corporate Travel JSON Tab */}
          {ingestionTab === 'travel' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Simulate Navan / Concur webhook json payload. Calculates Scope 3 flights (with Haversine fallbacks), hotels, and ground transport.
              </p>
              
              <div className="form-group">
                <label className="form-label">Mock Webhook Body (JSON)</label>
                <textarea 
                  className="json-textarea"
                  value={travelPayload}
                  onChange={(e) => setTravelPayload(e.target.value)}
                />
              </div>

              <button className="btn btn-primary" onClick={handleTravelTrigger}>
                <Code size={14} /> Trigger Webhook Import
              </button>
            </div>
          )}

          {/* Uploader status message */}
          {uploadStatus.message && (
            <div className={`error-banner`} style={{
              backgroundColor: uploadStatus.type === 'error' ? 'rgba(239, 68, 68, 0.1)' : 
                               uploadStatus.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(59, 130, 246, 0.1)',
              borderColor: uploadStatus.type === 'error' ? 'rgba(239, 68, 68, 0.2)' : 
                           uploadStatus.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(59, 130, 246, 0.2)',
              color: uploadStatus.type === 'error' ? '#fca5a5' : 
                     uploadStatus.type === 'success' ? '#a7f3d0' : '#bfdbfe',
              margin: 0
            }}>
              {uploadStatus.message}
            </div>
          )}
        </aside>

        {/* Analyst Review Board */}
        <main className="glass review-board">
          <div className="board-header">
            <h3>Audit Review Dashboard</h3>

            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              {/* Source filter */}
              <select
                className="select-input"
                style={{ fontSize: 12, padding: '4px 12px' }}
                value={selectedSourceFilter}
                onChange={(e) => setSelectedSourceFilter(e.target.value)}
              >
                <option value="">All Source APIs</option>
                <option value="SAP">SAP MM ERP</option>
                <option value="UTILITY">Utility Bills</option>
                <option value="TRAVEL">Corporate Travel</option>
              </select>

              {/* Status Board tabs */}
              <div className="board-tabs">
                <button 
                  className={`board-tab ${selectedStatusTab === 'PENDING' ? 'active' : ''}`}
                  onClick={() => setSelectedStatusTab('PENDING')}
                >
                  Pending ({analytics?.status_counts.PENDING || 0})
                </button>
                <button 
                  className={`board-tab suspicious ${selectedStatusTab === 'SUSPICIOUS' ? 'active' : ''}`}
                  onClick={() => setSelectedStatusTab('SUSPICIOUS')}
                >
                  Suspicious ({analytics?.status_counts.SUSPICIOUS || 0})
                </button>
                <button 
                  className={`board-tab failed ${selectedStatusTab === 'FAILED' ? 'active' : ''}`}
                  onClick={() => setSelectedStatusTab('FAILED')}
                >
                  Failed ({analytics?.status_counts.FAILED || 0})
                </button>
                <button 
                  className={`board-tab ${selectedStatusTab === 'APPROVED' ? 'active' : ''}`}
                  onClick={() => setSelectedStatusTab('APPROVED')}
                >
                  Approved ({analytics?.status_counts.APPROVED || 0})
                </button>
              </div>
            </div>
          </div>

          <div className="table-container">
            {rows.length === 0 ? (
              <div style={{ padding: 48, textAlignment: 'center', color: 'var(--text-muted)' }}>
                No ingestion rows found for this queue. Try uploading a sample CSV or triggering a Travel webhook on the left panel!
              </div>
            ) : (
              <table className="custom-table">
                <thead>
                  <tr>
                    <th>Record ID</th>
                    <th>Source</th>
                    <th>Date</th>
                    <th>Scope</th>
                    <th>Category</th>
                    <th>Emissions (kg CO2e)</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.id}>
                      <td style={{ fontWeight: 600 }}>#{r.id}</td>
                      <td>
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{r.source_type}</span>
                      </td>
                      <td>{r.activity_date || 'N/A'}</td>
                      <td>
                        {r.scope ? (
                          <span className={`badge badge-${r.scope.toLowerCase().replace('_', '')}`}>
                            {r.scope.replace('_', ' ')}
                          </span>
                        ) : '—'}
                      </td>
                      <td>{r.category || 'N/A'}</td>
                      <td>
                        {r.emissions_co2e_kg !== null ? (
                          <span style={{ fontWeight: 700 }}>
                            {r.emissions_co2e_kg.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg
                          </span>
                        ) : '—'}
                      </td>
                      <td>
                        <span className={`badge badge-${r.status.toLowerCase()}`}>
                          {r.status}
                        </span>
                      </td>
                      <td>
                        <button className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => openRowDetails(r)}>
                          <Eye size={12} /> Inspect
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </main>
      </div>

      {/* Row detail modal (Sidebar drawer) */}
      {selectedRow && detailedRowData && (
        <div className="modal-overlay" onClick={() => setSelectedRow(null)}>
          <div className="modal-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h2>Inspect Record #{detailedRowData.id}</h2>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                  Source API: {detailedRowData.source_type} | Uploaded by: {detailedRowData.uploaded_by}
                </div>
              </div>
              <button className="modal-close" onClick={() => setSelectedRow(null)}>
                <X size={24} />
              </button>
            </div>

            {/* Error Banner */}
            {modalError && (
              <div className="error-banner">
                <AlertOctagon size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                {modalError}
              </div>
            )}

            {/* Validation warning alerts */}
            {detailedRowData.validation_errors && detailedRowData.validation_errors.length > 0 && (
              <div className="error-banner" style={{ 
                backgroundColor: detailedRowData.status === 'FAILED' ? 'rgba(239,68,68,0.1)' : 'rgba(249,115,22,0.1)',
                borderColor: detailedRowData.status === 'FAILED' ? 'rgba(239,68,68,0.2)' : 'rgba(249,115,22,0.2)',
                color: detailedRowData.status === 'FAILED' ? '#fca5a5' : '#fed7aa',
              }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>Validation Alerts ({detailedRowData.validation_errors.length})</div>
                <ul style={{ paddingLeft: 16 }}>
                  {detailedRowData.validation_errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Normalization Outcome */}
            {detailedRowData.normalized_data && (
              <div className="glass" style={{ padding: 16, marginBottom: 24, borderLeft: '4px solid var(--accent-primary)' }}>
                <h4 style={{ marginBottom: 12, fontFamily: 'var(--font-heading)' }}>Normalized Carbon Calculation</h4>
                
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 13 }}>
                  <div>
                    <span className="form-label" style={{ marginBottom: 2 }}>Scope Mapping</span>
                    <span className={`badge badge-${detailedRowData.normalized_data.scope.toLowerCase().replace('_', '')}`}>
                      {detailedRowData.normalized_data.scope.replace('_', ' ')}
                    </span>
                  </div>
                  <div>
                    <span className="form-label" style={{ marginBottom: 2 }}>Normalized Emissions</span>
                    <span style={{ fontWeight: 700, color: 'var(--accent-primary)' }}>
                      {detailedRowData.normalized_data.co2e_kg.toLocaleString()} kg CO2e
                    </span>
                  </div>
                  <div>
                    <span className="form-label" style={{ marginBottom: 2 }}>Parsed Quantity</span>
                    <span>{detailedRowData.normalized_data.raw_quantity} {detailedRowData.normalized_data.raw_unit}</span>
                  </div>
                  <div>
                    <span className="form-label" style={{ marginBottom: 2 }}>Normalized Quantity</span>
                    <span>{detailedRowData.normalized_data.normalized_quantity.toFixed(1)} {detailedRowData.normalized_data.normalized_unit}</span>
                  </div>
                  <div style={{ gridColumn: 'span 2' }}>
                    <span className="form-label" style={{ marginBottom: 2 }}>Formula details</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{detailedRowData.normalized_data.description}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Raw JSON View / Editor */}
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span className="form-label" style={{ margin: 0 }}>Payload Content</span>
                {detailedRowData.status !== 'APPROVED' && (
                  <button 
                    className="btn btn-secondary" 
                    style={{ padding: '2px 8px', fontSize: 11 }}
                    onClick={() => setIsEditMode(!isEditMode)}
                  >
                    {isEditMode ? "Cancel" : <><Edit3 size={11} /> Override Raw Fields</>}
                  </button>
                )}
              </div>

              {isEditMode ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <textarea 
                    className="json-textarea"
                    style={{ height: 200 }}
                    value={editableJson}
                    onChange={(e) => setEditableJson(e.target.value)}
                  />
                  <button className="btn btn-primary" onClick={saveRowEdit} style={{ alignSelf: 'flex-end' }}>
                    <Check size={14} /> Recalculate & Re-verify
                  </button>
                </div>
              ) : (
                <pre style={{ 
                  backgroundColor: '#0d1117', 
                  color: '#e6edf3', 
                  padding: 12, 
                  borderRadius: 8, 
                  fontSize: 11,
                  fontFamily: 'monospace',
                  overflowX: 'auto',
                  border: '1px solid var(--border-color)',
                  maxHeight: 180
                }}>
                  {JSON.stringify(detailedRowData.raw_data, null, 2)}
                </pre>
              )}
            </div>

            {/* Audit Trail Timeline */}
            <div>
              <span className="form-label">Audit Trail History Log</span>
              <div className="timeline">
                {detailedRowData.audit_trail && detailedRowData.audit_trail.map((item, idx) => (
                  <div className="timeline-item" key={idx}>
                    <div className={`timeline-marker ${idx === 0 ? 'active' : ''}`} />
                    <div className="timeline-header">
                      <span>{item.action} by {item.user}</span>
                      <span className="timeline-time">
                        {new Date(item.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    {item.new_status && (
                      <div style={{ fontSize: 11, marginTop: 2 }}>
                        Status: <span className={`badge badge-${item.new_status.toLowerCase()}`} style={{ padding: '1px 4px', fontSize: 9 }}>{item.new_status}</span>
                      </div>
                    )}
                    {item.details?.validation_errors?.length > 0 && (
                      <div className="timeline-desc" style={{ color: 'var(--color-failed)' }}>
                        Errors: {item.details.validation_errors.join(', ')}
                      </div>
                    )}
                    {item.details?.message && (
                      <div className="timeline-desc">{item.details.message}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Bottom Actions */}
            {detailedRowData.status !== 'APPROVED' && (
              <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 16, marginTop: 16, display: 'flex', gap: 12 }}>
                {detailedRowData.status !== 'FAILED' && (
                  <button 
                    className="btn btn-primary" 
                    style={{ flex: 1 }}
                    onClick={() => approveRow(detailedRowData.id)}
                  >
                    <ShieldCheck size={16} /> Approve & Lock For Audit
                  </button>
                )}
                <button 
                  className="btn btn-secondary" 
                  style={{ flex: 1 }}
                  onClick={() => setSelectedRow(null)}
                >
                  Close
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
