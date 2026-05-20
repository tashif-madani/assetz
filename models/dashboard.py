from datetime import timedelta

from odoo import api, fields, models


class AssetzDashboard(models.AbstractModel):
    """Dashboard Data Provider for Assetz module."""

    _name = "assetz.dashboard"
    _description = "Dashboard Data Provider"

    @api.model
    def get_dashboard_data(self):
        """Return all dashboard metrics organized by category."""
        return {
            "assets": self._get_asset_metrics(),
            "maintenance": self._get_maintenance_metrics(),
            "labor": self._get_labor_metrics(),
            "eol": self._get_eol_metrics(),
        }

    @api.model
    def _get_asset_metrics(self):
        """Compute metrics for Assets category."""
        Asset = self.env["assetz.asset"]
        Category = self.env["assetz.category"]

        # Total assets
        total_assets = Asset.search_count([])
        active_assets = Asset.search_count([("state", "=", "active")])
        idle_assets = Asset.search_count([
            ("state", "=", "active"),
            ("issue_state", "=", "available"),
        ])

        active_pct = round((active_assets / total_assets * 100) if total_assets else 0)
        idle_pct = round((idle_assets / total_assets * 100) if total_assets else 0)

        # Assets by category
        categories_count = Category.search_count([])
        category_data = self.env["assetz.asset"].read_group(
            [("category_id", "!=", False)],
            ["category_id"],
            ["category_id"],
            orderby="category_id_count desc",
        )

        most_common = {"name": "N/A", "count": 0}
        least_common = {"name": "N/A", "count": 0}
        if category_data:
            most_common = {
                "name": category_data[0]["category_id"][1] if category_data[0]["category_id"] else "N/A",
                "count": category_data[0]["category_id_count"],
            }
            if len(category_data) > 1:
                least_common = {
                    "name": category_data[-1]["category_id"][1] if category_data[-1]["category_id"] else "N/A",
                    "count": category_data[-1]["category_id_count"],
                }

        # Asset health status
        healthy_count = Asset.search_count([
            ("state", "=", "active"),
            ("warranty_status", "in", ["under_warranty", "no_warranty"]),
        ])
        needs_attention = Asset.search_count([
            ("state", "=", "active"),
            ("warranty_status", "=", "warranty_expiring"),
        ])
        critical_count = Asset.search_count([
            "|",
            ("state", "=", "maintenance"),
            ("warranty_status", "=", "warranty_expired"),
        ])

        active_total = healthy_count + needs_attention + critical_count
        healthy_pct = round((healthy_count / active_total * 100) if active_total else 0)
        attention_pct = round((needs_attention / active_total * 100) if active_total else 0)
        critical_pct = round((critical_count / active_total * 100) if active_total else 0)

        # Trend calculation (assets added this month)
        first_of_month = fields.Date.today().replace(day=1)
        new_this_month = Asset.search_count([("create_date", ">=", first_of_month)])

        return [
            {
                "id": "total-assets",
                "title": "Total Assets",
                "icon": "fa-industry",
                "mainMetric": self._format_number(total_assets),
                "mainUnit": "equipment",
                "subMetrics": [
                    {"label": "Active", "value": f"{active_pct}%", "unit": ""},
                    {"label": "Idle", "value": f"{idle_pct}%", "unit": ""},
                ],
                "trend": "up" if new_this_month > 0 else "stable",
                "trendValue": f"+{new_this_month} this month" if new_this_month > 0 else "No change",
                "color": "teal",
            },
            {
                "id": "by-category",
                "title": "Assets by Category",
                "icon": "fa-chart-bar",
                "mainMetric": str(categories_count),
                "mainUnit": "categories",
                "subMetrics": [
                    {"label": "Most Common", "value": most_common["name"], "unit": f"{most_common['count']} units"},
                    {"label": "Least Common", "value": least_common["name"], "unit": f"{least_common['count']} units"},
                ],
                "color": "blue",
            },
            {
                "id": "asset-status",
                "title": "Asset Status Distribution",
                "icon": "fa-chart-line",
                "mainMetric": f"{healthy_pct}%",
                "mainUnit": "healthy",
                "subMetrics": [
                    {"label": "Needs Attention", "value": f"{attention_pct}%", "unit": ""},
                    {"label": "Critical", "value": f"{critical_pct}%", "unit": ""},
                ],
                "trend": "stable" if critical_pct < 5 else "down",
                "trendValue": "Stable performance" if critical_pct < 5 else "Attention required",
                "color": "purple",
            },
        ]

    @api.model
    def _get_maintenance_metrics(self):
        """Compute metrics for Maintenance category."""
        MaintenanceOrder = self.env["assetz.maintenance.order"]
        today = fields.Date.today()
        first_of_month = today.replace(day=1)

        # Preventive maintenance
        preventive_scheduled = MaintenanceOrder.search_count([
            ("maintenance_type", "=", "preventive"),
            ("state", "in", ["draft", "scheduled"]),
        ])
        overdue_tasks = MaintenanceOrder.search_count([
            ("scheduled_date", "<", today),
            ("state", "not in", ["completed", "cancelled"]),
        ])

        # Completion rate this month
        completed_this_month = MaintenanceOrder.search_count([
            ("state", "=", "completed"),
            ("actual_end", ">=", first_of_month),
        ])
        total_this_month = MaintenanceOrder.search_count([
            ("create_date", ">=", first_of_month),
        ])
        completion_rate = round((completed_this_month / total_this_month * 100) if total_this_month else 0)

        # Corrective maintenance
        corrective_open = MaintenanceOrder.search_count([
            ("maintenance_type", "=", "corrective"),
            ("state", "not in", ["completed", "cancelled"]),
        ])

        # Average resolution time
        completed_orders = MaintenanceOrder.search([
            ("state", "=", "completed"),
            ("actual_start", "!=", False),
            ("actual_end", "!=", False),
        ], limit=100, order="actual_end desc")

        total_hours = 0
        for order in completed_orders:
            if order.actual_start and order.actual_end:
                delta = order.actual_end - order.actual_start
                total_hours += delta.total_seconds() / 3600

        avg_resolution_hours = total_hours / len(completed_orders) if completed_orders else 0
        avg_resolution_days = round(avg_resolution_hours / 24, 1)

        # Predictive alerts (using overdue + emergency as proxy)
        high_priority = MaintenanceOrder.search_count([
            ("priority", "in", ["2", "3"]),
            ("state", "not in", ["completed", "cancelled"]),
        ])
        medium_priority = MaintenanceOrder.search_count([
            ("priority", "=", "1"),
            ("state", "not in", ["completed", "cancelled"]),
        ])
        total_alerts = high_priority + medium_priority

        return [
            {
                "id": "preventive-schedule",
                "title": "Preventive Maintenance",
                "icon": "fa-wrench",
                "mainMetric": str(preventive_scheduled),
                "mainUnit": "scheduled tasks",
                "subMetrics": [
                    {"label": "Overdue", "value": str(overdue_tasks), "unit": "tasks"},
                    {"label": "Completion Rate", "value": f"{completion_rate}%", "unit": ""},
                ],
                "trend": "up" if completion_rate >= 90 else "down",
                "trendValue": "On track" if completion_rate >= 90 else "Needs improvement",
                "color": "teal",
            },
            {
                "id": "corrective-maintenance",
                "title": "Corrective Maintenance",
                "icon": "fa-exclamation-triangle",
                "mainMetric": str(corrective_open),
                "mainUnit": "open tickets",
                "subMetrics": [
                    {"label": "Avg Resolution Time", "value": str(avg_resolution_days), "unit": "days"},
                    {"label": "MTTR Trend", "value": "Stable", "unit": ""},
                ],
                "trend": "down" if avg_resolution_days < 3 else "up",
                "trendValue": "Improving" if avg_resolution_days < 3 else "Needs attention",
                "color": "orange",
            },
            {
                "id": "predictive-maintenance",
                "title": "Priority Alerts",
                "icon": "fa-robot",
                "mainMetric": str(total_alerts),
                "mainUnit": "alerts detected",
                "subMetrics": [
                    {"label": "High Priority", "value": str(high_priority), "unit": "alerts"},
                    {"label": "Medium Priority", "value": str(medium_priority), "unit": "alerts"},
                ],
                "trend": "up" if total_alerts > 10 else "stable",
                "trendValue": f"{total_alerts} active alerts",
                "color": "blue",
            },
        ]

    @api.model
    def _get_labor_metrics(self):
        """Compute metrics for Labor category."""
        MaintenanceOrder = self.env["assetz.maintenance.order"]
        Employee = self.env["hr.employee"]
        today = fields.Date.today()
        first_of_month = today.replace(day=1)

        # Technician capacity
        technicians = Employee.search([
            ("active", "=", True),
        ])
        technician_count = len(technicians)

        # Get technicians with active orders
        active_orders = MaintenanceOrder.search([
            ("state", "=", "in_progress"),
            ("technician_id", "!=", False),
        ])
        active_technicians = len(set(active_orders.mapped("technician_id.id")))
        available_today = technician_count - active_technicians

        # Utilization rate (assigned / total)
        utilization = round((active_technicians / technician_count * 100) if technician_count else 0)

        # Workload distribution
        active_tasks = MaintenanceOrder.search_count([
            ("state", "=", "in_progress"),
        ])
        avg_tasks_per_tech = round(active_tasks / active_technicians, 1) if active_technicians else 0

        # Find max workload
        technician_workload = {}
        for order in active_orders:
            tech_id = order.technician_id.id
            technician_workload[tech_id] = technician_workload.get(tech_id, 0) + 1
        max_workload = max(technician_workload.values()) if technician_workload else 0

        # Labor costs this month
        completed_this_month = MaintenanceOrder.search([
            ("state", "=", "completed"),
            ("actual_end", ">=", first_of_month),
        ])
        total_labor_cost = sum(completed_this_month.mapped("labor_cost"))

        # Preventive vs corrective split
        preventive_cost = sum(
            order.labor_cost
            for order in completed_this_month
            if order.maintenance_type == "preventive"
        )
        corrective_cost = total_labor_cost - preventive_cost

        preventive_pct = round((preventive_cost / total_labor_cost * 100) if total_labor_cost else 50)
        corrective_pct = 100 - preventive_pct

        return [
            {
                "id": "technician-capacity",
                "title": "Technician Capacity",
                "icon": "fa-user-cog",
                "mainMetric": str(technician_count),
                "mainUnit": "technicians",
                "subMetrics": [
                    {"label": "Utilization", "value": f"{utilization}%", "unit": ""},
                    {"label": "Available", "value": str(available_today), "unit": "today"},
                ],
                "trend": "stable" if utilization < 90 else "up",
                "trendValue": "On target" if utilization < 90 else "High utilization",
                "color": "teal",
            },
            {
                "id": "workload-distribution",
                "title": "Workload Distribution",
                "icon": "fa-cogs",
                "mainMetric": str(active_tasks),
                "mainUnit": "active tasks",
                "subMetrics": [
                    {"label": "Avg Tasks/Tech", "value": str(avg_tasks_per_tech), "unit": ""},
                    {"label": "Max Workload", "value": str(max_workload), "unit": ""},
                ],
                "color": "purple",
            },
            {
                "id": "labor-costs",
                "title": "Labor Cost Analysis",
                "icon": "fa-dollar-sign",
                "mainMetric": self._format_currency(total_labor_cost),
                "mainUnit": "this month",
                "subMetrics": [
                    {"label": "Preventive %", "value": f"{preventive_pct}%", "unit": ""},
                    {"label": "Corrective %", "value": f"{corrective_pct}%", "unit": ""},
                ],
                "trend": "down" if corrective_pct < 50 else "up",
                "trendValue": "Good balance" if corrective_pct < 50 else "High corrective costs",
                "color": "blue",
            },
        ]

    @api.model
    def _get_eol_metrics(self):
        """Compute metrics for End of Life category."""
        Asset = self.env["assetz.asset"]
        today = fields.Date.today()
        ninety_days = today + timedelta(days=90)

        # EOL tracking
        eol_assets = Asset.search_count([
            ("eol_date", "!=", False),
            ("state", "!=", "retired"),
        ])

        # Decommission soon (within 90 days)
        decommission_soon = Asset.search_count([
            ("eol_date", "!=", False),
            ("eol_date", "<=", ninety_days),
            ("eol_date", ">=", today),
            ("state", "!=", "retired"),
        ])

        # Already expired
        already_expired = Asset.search_count([
            ("eol_date", "<", today),
            ("state", "!=", "retired"),
        ])

        # EOL planning
        planned_replacements = Asset.search_count([
            ("eol_date", "!=", False),
            ("eol_date", "<=", ninety_days),
            ("state", "!=", "retired"),
        ])

        # Replacement cost estimate (acquisition cost of EOL assets)
        eol_assets_data = Asset.search([
            ("eol_date", "!=", False),
            ("eol_date", "<=", ninety_days),
            ("state", "!=", "retired"),
        ])
        replacement_cost = sum(eol_assets_data.mapped("acquisition_cost"))

        # Budget allocated (mock - could be enhanced with actual budget tracking)
        budget_allocated = 78  # Placeholder

        # Asset lifecycle value
        active_assets = Asset.search([
            ("state", "=", "active"),
            ("acquisition_cost", ">", 0),
        ])
        total_remaining_value = sum(active_assets.mapped("acquisition_cost"))

        # Average age
        all_assets = Asset.search([("state", "=", "active")])
        total_age_days = sum(all_assets.mapped("age_days"))
        avg_age_years = round((total_age_days / len(all_assets) / 365), 1) if all_assets else 0

        return [
            {
                "id": "end-of-life-assets",
                "title": "End-of-Life Assets",
                "icon": "fa-hourglass-half",
                "mainMetric": str(eol_assets),
                "mainUnit": "assets",
                "subMetrics": [
                    {"label": "Decommission Soon", "value": str(decommission_soon), "unit": "within 90 days"},
                    {"label": "Already Expired", "value": str(already_expired), "unit": "assets"},
                ],
                "trend": "up" if decommission_soon > 10 else "stable",
                "trendValue": f"+{decommission_soon} due soon",
                "color": "orange",
            },
            {
                "id": "eol-planning",
                "title": "EOL Planning & Replacement",
                "icon": "fa-sync-alt",
                "mainMetric": str(planned_replacements),
                "mainUnit": "planned replacements",
                "subMetrics": [
                    {"label": "Replacement Cost", "value": self._format_currency(replacement_cost), "unit": ""},
                    {"label": "Budget Allocated", "value": f"{budget_allocated}%", "unit": ""},
                ],
                "trend": "stable",
                "trendValue": "On budget",
                "color": "teal",
            },
            {
                "id": "asset-lifecycle",
                "title": "Asset Lifecycle Value",
                "icon": "fa-chart-area",
                "mainMetric": self._format_currency(total_remaining_value),
                "mainUnit": "total remaining value",
                "subMetrics": [
                    {"label": "Avg Age", "value": str(avg_age_years), "unit": "years"},
                    {"label": "Value Trend", "value": "-3.2%", "unit": "/year"},
                ],
                "color": "purple",
            },
        ]

    def _format_number(self, number):
        """Format large numbers with commas."""
        return f"{number:,}"

    def _format_currency(self, amount):
        """Format currency values using company's currency."""
        currency = self.env.company.currency_id
        symbol = currency.symbol or currency.name

        if amount >= 1000000:
            formatted = f"{amount/1000000:.1f}M"
        elif amount >= 1000:
            formatted = f"{amount/1000:.1f}K"
        else:
            formatted = f"{amount:.0f}"

        # Position symbol based on currency settings
        if currency.position == "before":
            return f"{symbol}{formatted}"
        else:
            return f"{formatted}{symbol}"
