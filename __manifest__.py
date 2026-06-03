{
    "name": "Assetz - Asset Tracking",
    "version": "18.0.1.0.0",
    "category": "Assets",
    "summary": "End-to-end asset tracking and management with QR codes, EOL tracking, and AI recommendations",
    "description": """
Assetz - Asset Tracking for Odoo 18
===================================

A comprehensive, industry-agnostic asset tracking application that helps organizations
manage their physical assets throughout their entire lifecycle.

Key Features:
-------------
- **Asset Registry**: Centralized database of all organizational assets
- **Custom Categories**: Define categories with dynamic attributes
- **QR Code Generation**: Auto-generate QR codes for easy asset identification
- **Location Tracking**: Hierarchical location management with GPS support
- **Movement Logging**: Track all asset movements between locations
- **Asset Issue Workflow**: Flexible issuance to employees, departments, locations, projects
- **Asset Requests**: Employee request workflow with multi-level approval
- **EOL Management**: Track End of Life dates with automated reminders
- **AI Recommendations**: OpenAI GPT-4 integration for EOL predictions
- **Bulk Import**: Import assets from CSV/Excel files
- **Industry Presets**: Pre-configured settings for IT, Manufacturing, Healthcare, etc.

Configuration:
--------------
All features are configurable through Settings → Assetz:
- Enable/disable individual features
- Industry presets for quick configuration
- Category-level overrides
- Multi-company support
    """,
    "author": "ThetaDirect",
    "website": "https://www.thetadirect.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "hr",
        "purchase",
        "stock",
        "account",
        "product",
        "sale_management",
        "sale_renting",
        "industry_fsm",
        "industry_fsm_stock",
    ],
    "external_dependencies": {
        "python": ["qrcode", "openpyxl", "openai", "PyPDF2", "python-docx", "anthropic", "pdfplumber", "pdf2image", "pytesseract", "xlsxwriter"],
    },
    "data": [
        # Security
        "security/security.xml",
        "security/ir.model.access.csv",
        # Data
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        # Menus - Must load early so other views can reference parent menus
        "views/menus.xml",
        # Dashboard
        "views/dashboard_views.xml",
        # Views - Configuration
        "views/category_views.xml",
        "views/location_views.xml",
        "views/agreement_views.xml",
        "views/res_config_settings_views.xml",
        # Views - Operations
        "views/issue_order_views.xml",
        "views/asset_request_views.xml",
        "views/reservation_views.xml",
        "views/purchase_request_views.xml",
        "views/sale_order_views.xml",
        "views/project_task_views.xml",
        "views/service_product_views.xml",
        "views/import_wizard_views.xml",
        # Views - QR Code Templates
        "views/asset_qr_templates.xml",

        # Wizards - AI Asset Creation
        "wizard/ai_asset_wizard_views.xml",
        # Views - Assets (last because it contains menus referencing other actions)
        "views/asset_views.xml",
        # Views - Warranty/Contract Management
        "views/service_contract_views.xml",
        "views/warranty_claim_views.xml",
        # Views - Maintenance (Standalone)
        "views/maintenance_order_views.xml",
        "views/maintenance_schedule_views.xml",
        "views/maintenance_checklist_views.xml",
        "views/maintenance_team_views.xml",
        "views/technician_skill_views.xml",
        # Views - Report Wizard
        "views/report_wizard_views.xml",
        # Security for Report Wizard (must load after wizard model is registered)
        "security/report_wizard_security.xml",
        # Reports - PDF Templates
        "report/report_templates.xml",
        # Wizards - Warranty/Contract
        "wizard/wo_close_wizard_views.xml",
        "wizard/claim_wizard_views.xml",
        # Wizards - AI Checklist Recommendations
        "wizard/ai_checklist_wizard_views.xml",
        # Wizards - Maintenance
        "wizard/signature_wizard_views.xml",
        "wizard/create_checklist_wizard_views.xml",
        "wizard/technician_schedule_wizard_views.xml",
        # Security & Crons for warranty (must be after views so models are registered)
        "security/warranty_security.xml",
        "data/warranty_cron.xml",
    ],
    "demo": [],
    "assets": {
        "web.assets_backend": [
            "assetz/static/src/css/dashboard.css",
            "assetz/static/src/js/dashboard/*.js",
            "assetz/static/src/xml/dashboard_templates.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
