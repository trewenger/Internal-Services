# API Service Network

**Internal API service library with shared integrations**

A production-grade Python library providing reusable API clients and utilities for enterprise system integrations. Built to streamline internal business automation by centralizing common service interactions into a modular, maintainable architecture.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## Overview

API Service Network is a monorepo containing:

1. **`src/common/`** - Shared Python library with API clients for:
   - Email notifications (SMTP2GO)
   - Fishbowl Advanced inventory management
   - Google Sheets integration
   - Microsoft Graph API
   - Intuiflow scheduling platform
   - Common utilities (logging, CSV export, SQL query loading)

2. **Applications** - Production services utilizing the common library:
   - **RetailInventoryManager** - Web-based inventory synchronization system (Flask + APScheduler)
   - **VariousInternalServices** - Collection of scheduled automation services for operations and reporting

This architecture promotes code reuse, consistent patterns, and separation of concerns across internal automation projects.

---

## Project Structure

```
API-Service-Network/
├── src/
│   └── common/                    # Shared library (installable Python package)
│       ├── Clients/               # API client modules
│       │   ├── Email/            # SMTP2GO email client
│       │   ├── Fishbowl/         # Fishbowl Advanced REST API
│       │   ├── Google/           # Google Sheets API
│       │   ├── Microsoft/        # Microsoft Graph API
│       │   └── Intuiflow/        # Intuiflow manufacturing API
│       └── Utils/                 # Shared utilities
│           ├── Logging.py        # Session logging
│           └── Utils.py          # CSV export, SQL loader
│
├── RetailInventoryManager/        # Inventory sync web application
│   ├── app.py                    # Flask application
│   ├── sync.py                   # Fishbowl sync orchestration
│   ├── data.py                   # Data layer & error logging
│   ├── templates/                # HTML templates
│   ├── static/                   # CSS/JS assets
│   └── queries/                  # SQL query files
│
├── VariousInternalServices/       # Scheduled automation services
│   ├── OnTimePerformance.py      # Order fulfillment tracking
│   ├── TaxSystemHealth.py        # Tax compliance validation
│   ├── VendorTracker.py          # Parts at vendor monitoring
│   ├── WipUpdate.py              # WIP tracker updates
│   ├── Queries/                  # SQL query files (.gitignored)
│   └── Outputs/                  # CSV exports (.gitignored)
│
├── pyproject.toml                 # Common library package config
├── README.md                      # This file
└── LICENSE                        # MIT License
```

---

## Common Library (`src/common/`)

The shared library provides production-tested API clients with consistent error handling and authentication patterns.

### Email Client

Send HTML emails with attachments via SMTP2GO REST API.

```python
from common.Clients.Email.EmailApi import send_email

send_email(
    subject="Test Email",
    html_body="<h1>Hello World</h1>",
    recipients=["user@example.com"],
    attachments=["/path/to/file.pdf"]  # Optional
)
```

**Environment Variables Required:**
- `SMTP2GO_API_KEY`
- `SENDER_EMAIL` (optional, for default sender address)

---

### Fishbowl Client

Interact with Fishbowl Advanced inventory system via REST API.

```python
from common.Clients.Fishbowl.FishbowlSession import FishbowlSession

# Create session (auto-login with retry logic)
fb = FishbowlSession(is_test_db=False, login_attempts=5)

# Execute SQL query
result = fb.query("SELECT * FROM product LIMIT 10")
print(result["data"])

# Bulk inventory cycle import
data = [["SKU", "Location", "Qty"], ["SKU-001", "Retail", "100"]]
fb.cycle_inventory(data)

# Logout
fb.logout()
```

**Environment Variables Required:**
- `FISHBOWL_SERVER_ADDRESS`
- `FISHBOWL_PROD_PORT` / `FISHBOWL_TEST_PORT`
- `FISHBOWL_APP_NAME`, `FISHBOWL_APP_DESCRIPTION`, `FISHBOWL_APP_ID`
- `FISHBOWL_USERNAME`, `FISHBOWL_PASSWORD`
- `FISHBOWL_BEARER_TOKEN`

---

### Google Sheets Client

Read and write Google Sheets using service account authentication.

```python
from common.Clients.Google.GoogleSession import GoogleSession

# Initialize with sheet ID
sheet = GoogleSession(sheet_id="your-sheet-id")

# Read range
values = sheet.read_range("Sheet1", "A1:C10")

# Update range
sheet.update_range("Sheet1", "A1:B2", [["Header1", "Header2"], ["Val1", "Val2"]])

# Append rows
sheet.append_rows("Sheet1", "A1", [["Row1", "Data"], ["Row2", "Data"]])
```

**Environment Variables Required:**
- `GOOGLE_SERVICE_SCOPES` (e.g., `https://www.googleapis.com/auth/spreadsheets`)
- `GOOGLE_CREDENTIALS_PATH` (path to service account JSON file)

**Note:** You must provide your own `credentials.json` file. See [Google Workspace Guide](https://developers.google.com/workspace/guides/create-credentials).

---

### Microsoft Graph Client

Interact with OneDrive/SharePoint Excel files via Microsoft Graph API.

```python
from common.Clients.Microsoft.GraphSession import GraphSession

# Initialize with user and file path
graph = GraphSession(
    user_principle_name="user@company.com",
    OneDrive_file_path="Shared Documents/Reports/data.xlsx"
)

# Read Excel range
data = graph.get_excel_range("Sheet1", "A1:C10")

# Update Excel range
graph.update_excel_range("Sheet1", "A1", [["New", "Data"], ["Row2", "Data"]])
```

**Environment Variables Required:**
- `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`
- `GRAPH_PFX_PATH`, `GRAPH_PFX_PASSWORD`, `GRAPH_PFX_THUMBPRINT`

---

### Intuiflow Client

Manufacturing planning API for BOMs, work orders, and scheduling.

```python
from common.Clients.Intuiflow.IntuiflowApi import get_open_wo, create_import

# Get open work orders
result = get_open_wo(is_test_environment=False)
print(result["data"])

# Create import session
import_session = create_import(import_mode="Update", is_test_environment=False)
```

**Environment Variables Required:**
- `INTUIFLOW_PROD_ADDRESS`, `INTUIFLOW_PROD_TOKEN`
- `INTUIFLOW_TEST_ADDRESS`, `INTUIFLOW_TEST_TOKEN`

---

### Utilities

```python
from common.Utils.Logging import SessionLog
from common.Utils.Utils import load_query, csv_export

# Session logging
log = SessionLog()
log.log("function_name", "Operation completed", is_error=False)
if log.error_flag():
    print("Errors occurred:", log.get_log())

# Load SQL query from file (searches project directory)
query = load_query("my_query.sql")

# Export data to CSV
data = [{"col1": "val1", "col2": "val2"}]
csv_export(data, "output.csv")
```

---

## Installation

### Install Dependencies

From the repository root:

```bash
# Install all dependencies (includes the common library)
pip install -r requirements.txt
```

The `requirements.txt` file includes an editable install of the `common` library from this repository, so all dependencies and the shared library will be installed in one step.

### Environment Variables

Each application and client requires specific environment variables. Create a `.env` file in your application directory:

```env
# Example .env structure (see specific client docs above)
SMTP2GO_API_KEY=your_key_here
FISHBOWL_SERVER_ADDRESS=localhost
FISHBOWL_PROD_PORT=10
# ... etc
```

Load environment variables in your application:

```python
from dotenv import load_dotenv
import os

load_dotenv()  # Must be called BEFORE importing common clients
```

---

## Applications

### RetailInventoryManager

A production Flask web application for synchronizing retail website inventory with Fishbowl inventory management.

**Features:**
- Real-time inventory tracking with web dashboard
- Automated background sync jobs (APScheduler)
- Manual and automated operational modes
- Error logging with email notifications
- Audit trails for all inventory changes
- Thread-safe JSON data storage

**Quick Start:**

```bash
cd RetailInventoryManager

# Install dependencies
pip install -r requirements.txt

# Configure .env (see RetailInventoryManager/claude.md for details)
cp .env.example .env
# Edit .env with your credentials

# Run development server
python app.py

# Run production server
python prod_server.py
```

Access the dashboard at `http://localhost:5000`

For detailed documentation, see [`RetailInventoryManager/claude.md`](./RetailInventoryManager/claude.md).

---

### VariousInternalServices

A collection of automated internal services for business operations and reporting. Each service is designed to run on a schedule (via cron, Task Scheduler, etc.) and utilizes the common library for Fishbowl, Google Sheets, and email integration.

**Services:**

#### OnTimePerformance
Tracks order fulfillment performance by syncing Fishbowl order data to Google Sheets for analysis.

- Queries Fishbowl for completed orders from the previous day
- Automatically pastes results to Google Sheet database
- Sends email summary reports after each run
- Updates "date last updated" fields across multiple report sheets

```python
from VariousInternalServices.OnTimePerformance import on_time_performance

on_time_performance(
    result_recipients=["admin@example.com"],
    custom_headers=["OrderType", "SO", "DateFulfilled", "LeadTime"],
    query_name="OnTimePerformance.sql",
    last_row=200000
)
```

#### TaxSystemHealth
Validates tax compliance configuration in Fishbowl by checking product tax codes and customer exemption statuses.

- Queries Fishbowl for products missing tax codes
- Identifies customer accounts with incorrect exemption settings
- Sends detailed error reports when configuration issues are found
- Helps maintain sales tax compliance

```python
from VariousInternalServices.TaxSystemHealth import tax_system_health

tax_system_health(
    result_recipients=["accounting@example.com"],
    product_query_name="TaxHealthProductCheck",
    customer_query_name="TaxHealthCustomerCheck"
)
```

#### VendorTracker
Monitors parts currently at external vendors (outsourced manufacturing) and updates a Google Sheet tracker.

- Discovers quantity of parts shipped to vendors but not yet received
- Validates WIP (Work In Progress) name custom fields in Fishbowl
- Cross-references part names with existing WIP tracker entries
- Alerts on missing or unmatched WIP names

```python
from VariousInternalServices.VendorTracker import vendor_tracker

vendor_tracker(
    email_rec=["operations@example.com"],
    column_order=["PartNumber", "Description", "Qty", "WipName"],
    sheet_name="import",
    query_name="VendorTracker"
)
```

#### WipUpdate
Comprehensive Work In Progress (WIP) tracker update that archives historical data and imports current Fishbowl inventory status.

- Archives previous week's backorder and shipment data
- Queries Fishbowl for:
  - Last week shipped quantities
  - Six month shipped quantities
  - Current backorder (on-order) quantities
- Exports data to CSV files for historical records
- Updates multiple Google Sheet tabs with current data
- Validates column positions to prevent data corruption

```python
from VariousInternalServices.WipUpdate import wip_update

wip_update(
    email_recipients=["inventory@example.com"],
    last_week_ship_query_name="WipLastWeekShip",
    six_month_ship_query_name="WipSixMonthShip",
    bo_query_name="WipBO"
)
```

**Common Features Across All Services:**
- Automated email notifications with run summaries
- Session logging with error tracking
- Environment variable configuration (no hardcoded credentials)
- Graceful error handling with detailed logging
- SQL queries stored in separate `.sql` files for maintainability

**Setup:**

```bash
cd VariousInternalServices

# Configure .env file with required credentials
# (See individual service docstrings for specific variables)

# Create SQL query files in Queries/ folder
# Example: Queries/OnTimePerformance.sql

# Run individual services
python -c "from OnTimePerformance import on_time_performance; on_time_performance(['admin@example.com'], [], 'OnTimePerformance.sql')"

# Or schedule with cron (Linux/Mac)
# 0 9 * * * cd /path/to/VariousInternalServices && python -c "from OnTimePerformance import on_time_performance; on_time_performance(['admin@example.com'], [], 'OnTimePerformance.sql')"

# Or schedule with Task Scheduler (Windows)
```

**Environment Variables Required:**

All services require the standard Fishbowl, Google Sheets, and SMTP2GO credentials (see Common Library section). Additional service-specific variables:

```env
# OnTimePerformance
ON_TIME_PERFORMANCE_SHEET_ID=your_sheet_id
ON_TIME_PERFORMANCE_SHEET_URL=your_sheet_url

# VendorTracker
VENDOR_TRACKER_SHEET_ID=your_sheet_id
VENDOR_TRACKER_SHEET_URL=your_sheet_url

# WipUpdate
WIP_TRACKER_ID=your_sheet_id
```

---

## Development

### Requirements

- Python 3.10+
- Virtual environment recommended

### Setup Development Environment

```bash
# Clone repository
git clone <repository-url>
cd API-Service-Network

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install all dependencies (includes common library)
pip install -r requirements.txt
```

### Adding New Clients

To add a new API client to the common library:

1. Create a new directory under `src/common/Clients/YourService/`
2. Implement client modules following existing patterns:
   - Environment variable configuration
   - Session/authentication management
   - Error handling with meaningful messages
   - Type hints and docstrings
3. Add `__init__.py` to expose public API
4. Update this README with usage examples

### Best Practices

- **Environment Variables**: All credentials/secrets must use environment variables, never hardcoded
- **Error Handling**: Use try/except blocks and log errors appropriately
- **Thread Safety**: For shared resources, use locks (see `data.py` in RetailInventoryManager)
- **Documentation**: Include docstrings and update README for new features
- **Testing**: Test against development/test environments before production

---

## Use Cases

This library was built for production use and currently powers:

- Automated inventory synchronization between ERP and e-commerce systems
- Order fulfillment performance tracking and reporting
- Tax compliance validation and monitoring
- Vendor parts tracking and WIP management
- Scheduled report generation and distribution via email
- Data pipeline orchestration between business systems
- Manufacturing planning and scheduling

Potential use cases for others:
- Multi-system integration projects
- Business process automation
- Data synchronization workflows
- Internal tooling and dashboards

---

## Support & Maintenance

**Important Notice:**

This repository is provided AS-IS for reference and potential reuse by others. It was built for internal business use and is shared publicly to demonstrate production Python integration patterns.

**No support is provided.** Issues and pull requests will not be actively monitored or addressed. You are welcome to fork and adapt for your own needs.

If you choose to use this code:
- Understand the dependencies and APIs being integrated
- Test thoroughly in your own environment
- Adapt to your specific requirements
- Take responsibility for security and credential management

---

## Security Considerations

### Credential Management

- **Never commit credentials** - Use `.env` files (excluded via `.gitignore`)
- **Service Accounts** - Google and Microsoft clients require service account credentials
- **API Keys** - SMTP2GO, Intuiflow, and Fishbowl require API keys/tokens
- **Certificate Authentication** - Microsoft Graph uses PFX certificate authentication

### Network Security

- Clients make outbound HTTPS requests to third-party APIs
- Fishbowl client communicates with local/network Fishbowl server
- Review firewall rules and network policies before deployment

### Data Privacy

- This library handles sensitive business data (inventory, orders, customer info)
- Implement appropriate access controls in your applications
- Follow data retention and privacy policies for your organization

---

## License

This project is licensed under the MIT License with emphasis on AS-IS provision - see the [LICENSE](./LICENSE) file for details.

**TL;DR:** You can use this code freely, but there is absolutely no warranty or support. Use at your own risk.

---

## Acknowledgments

Built with production use in mind, leveraging:
- Flask - Web framework
- APScheduler - Background job scheduling
- Google API Client - Google Sheets integration
- MSAL - Microsoft authentication
- Requests - HTTP client library

---

## Roadmap

Planned additions (no timeline or commitment):
- Additional API clients (Shopify, QuickBooks, etc.)
- Improved error handling and retry logic
- More comprehensive logging utilities
- Additional applications and automations
- Unit tests and integration tests

**Due to use in production environments, contributions are not welcome at this time.**
