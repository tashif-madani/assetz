from odoo import http
from odoo.http import request


class DashboardController(http.Controller):
    """Controller for Asset Dashboard API endpoints."""

    @http.route("/assetz/dashboard/data", type="json", auth="user")
    def get_dashboard_data(self):
        """Return all dashboard metrics for the logged-in user's company."""
        return request.env["assetz.dashboard"].get_dashboard_data()

    @http.route("/assetz/dashboard/category/<string:category>", type="json", auth="user")
    def get_category_data(self, category):
        """Return metrics for a specific category."""
        dashboard = request.env["assetz.dashboard"]
        data = dashboard.get_dashboard_data()
        return data.get(category, [])

    @http.route("/assetz/dashboard/refresh", type="json", auth="user")
    def refresh_dashboard(self):
        """Force refresh dashboard data (useful for real-time updates)."""
        return request.env["assetz.dashboard"].get_dashboard_data()
