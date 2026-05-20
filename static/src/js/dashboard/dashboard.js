/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * VoiceNarrator - Text-to-Speech service for dashboard metrics
 */
class VoiceNarrator {
    constructor() {
        this.synth = window.speechSynthesis || null;
        this.currentUtterance = null;
        this.enabled = true;
        this.rate = 0.9;
        this.pitch = 1.0;
        this.volume = 1.0;
        this.voice = null;
        this._selectVoice();
    }

    _selectVoice() {
        if (!this.synth) return;
        const setVoice = () => {
            const voices = this.synth.getVoices();
            const preferredVoices = ["Google US English", "Google UK English Female", "Samantha", "Alex"];
            for (const preferred of preferredVoices) {
                const found = voices.find(v => v.name.includes(preferred));
                if (found) {
                    this.voice = found;
                    return;
                }
            }
            const englishVoice = voices.find(v => v.lang.startsWith("en"));
            if (englishVoice) this.voice = englishVoice;
        };
        if (this.synth.onvoiceschanged !== undefined) {
            this.synth.onvoiceschanged = setVoice;
        }
        setVoice();
    }

    _generateNarration(card) {
        if (!card) return "";
        let narration = [`${card.title}.`, `${card.mainMetric} ${card.mainUnit}.`];
        if (card.subMetrics) {
            for (const metric of card.subMetrics) {
                let text = `${metric.label}: ${metric.value}`;
                if (metric.unit) text += ` ${metric.unit}`;
                narration.push(text + ".");
            }
        }
        if (card.trend && card.trendValue) {
            const trendWord = card.trend === "up" ? "Trend up" : card.trend === "down" ? "Trend down" : "Stable";
            narration.push(`${trendWord}: ${card.trendValue}.`);
        }
        return narration.join(" ");
    }

    speak(card) {
        if (!this.synth || !this.enabled) return;
        this.stop();
        const text = this._generateNarration(card);
        if (!text) return;
        this.currentUtterance = new SpeechSynthesisUtterance(text);
        this.currentUtterance.rate = this.rate;
        this.currentUtterance.pitch = this.pitch;
        this.currentUtterance.volume = this.volume;
        if (this.voice) this.currentUtterance.voice = this.voice;
        this.synth.speak(this.currentUtterance);
    }

    stop() {
        if (this.synth) {
            this.synth.cancel();
            this.currentUtterance = null;
        }
    }

    toggle() {
        this.enabled = !this.enabled;
        if (!this.enabled) this.stop();
        return this.enabled;
    }
}

/**
 * MetricCard Component - Displays a single metric card
 */
class MetricCard extends Component {
    static template = "assetz.MetricCard";
    static props = {
        card: Object,
    };

    getTrendEmoji() {
        const { trend } = this.props.card;
        if (trend === "up") return "📈";
        if (trend === "down") return "📉";
        return "➡️";
    }

    getProgressWidth(value) {
        if (typeof value === "string") {
            const numMatch = value.match(/[\d.]+/);
            if (numMatch) {
                const num = parseFloat(numMatch[0]);
                if (value.includes("%")) return Math.min(num, 100);
                return Math.min(num * 10, 100);
            }
        }
        if (typeof value === "number") return Math.min(value * 10, 100);
        return 50;
    }

    getIcon() {
        const icon = this.props.card.icon || "fa-chart-bar";
        if (icon.startsWith("fa-")) return icon;
        return `fa-${icon}`;
    }
}

/**
 * CategorySidebar Component - Navigation sidebar for categories
 */
class CategorySidebar extends Component {
    static template = "assetz.CategorySidebar";
    static props = {
        selectedCategory: String,
        expanded: Boolean,
        onCategoryChange: Function,
        onToggle: Function,
    };

    get categories() {
        return [
            { id: "assets", label: "Assets", icon: "fa-industry", description: "Equipment & inventory" },
            { id: "maintenance", label: "Maintenance", icon: "fa-wrench", description: "PM, CM & priorities" },
            { id: "labor", label: "Labor", icon: "fa-user-cog", description: "Team & workload" },
            { id: "eol", label: "End of Life", icon: "fa-hourglass-half", description: "Lifecycle management" },
        ];
    }

    onCategoryClick(categoryId) {
        this.props.onCategoryChange(categoryId);
    }

    onToggleClick() {
        this.props.onToggle();
    }

    isSelected(categoryId) {
        return this.props.selectedCategory === categoryId;
    }
}

/**
 * AssetzDashboard - Main dashboard component
 */
export class AssetzDashboard extends Component {
    static template = "assetz.Dashboard";
    static components = { MetricCard, CategorySidebar };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            selectedCategory: "assets",
            currentCardIndex: 0,
            cards: [],
            allData: {},
            loading: true,
            voiceEnabled: false,  // Voice off by default
            sidebarExpanded: true,
        });

        this.containerRef = useRef("container");
        this.touchStart = 0;
        this.touchEnd = 0;
        this.narrator = new VoiceNarrator();

        onMounted(() => {
            this.loadDashboardData();
            this.setupKeyboardNavigation();
            this.setupTouchNavigation();
        });

        onWillUnmount(() => {
            this.removeKeyboardNavigation();
            this.removeTouchNavigation();
            this.narrator.stop();
        });
    }

    async loadDashboardData() {
        try {
            const data = await this.orm.call("assetz.dashboard", "get_dashboard_data", []);
            this.state.allData = data;
            this.state.cards = data[this.state.selectedCategory] || [];
            this.state.loading = false;
            if (this.state.voiceEnabled && this.state.cards.length > 0) {
                this.speakCurrentCard();
            }
        } catch (error) {
            console.error("Failed to load dashboard data:", error);
            this.state.loading = false;
        }
    }

    setupKeyboardNavigation() {
        this.keydownHandler = this.handleKeydown.bind(this);
        window.addEventListener("keydown", this.keydownHandler);
    }

    removeKeyboardNavigation() {
        window.removeEventListener("keydown", this.keydownHandler);
    }

    setupTouchNavigation() {
        const container = this.containerRef.el;
        if (container) {
            this.touchStartHandler = this.handleTouchStart.bind(this);
            this.touchEndHandler = this.handleTouchEnd.bind(this);
            container.addEventListener("touchstart", this.touchStartHandler, { passive: true });
            container.addEventListener("touchend", this.touchEndHandler, { passive: true });
        }
    }

    removeTouchNavigation() {
        const container = this.containerRef.el;
        if (container) {
            container.removeEventListener("touchstart", this.touchStartHandler);
            container.removeEventListener("touchend", this.touchEndHandler);
        }
    }

    handleKeydown(event) {
        const { cards, currentCardIndex } = this.state;
        if (event.key === "ArrowDown" && currentCardIndex < cards.length - 1) {
            event.preventDefault();
            this.goToCard(currentCardIndex + 1);
        } else if (event.key === "ArrowUp" && currentCardIndex > 0) {
            event.preventDefault();
            this.goToCard(currentCardIndex - 1);
        } else if (event.key === "Escape") {
            this.closeDashboard();
        }
    }

    handleTouchStart(event) {
        this.touchStart = event.targetTouches[0].clientY;
    }

    handleTouchEnd(event) {
        this.touchEnd = event.changedTouches[0].clientY;
        this.handleSwipe();
    }

    handleSwipe() {
        if (!this.touchStart || !this.touchEnd) return;
        const distance = this.touchStart - this.touchEnd;
        const { cards, currentCardIndex } = this.state;
        if (distance > 50 && currentCardIndex < cards.length - 1) {
            this.goToCard(currentCardIndex + 1);
        } else if (distance < -50 && currentCardIndex > 0) {
            this.goToCard(currentCardIndex - 1);
        }
        this.touchStart = 0;
        this.touchEnd = 0;
    }

    goToCard(index) {
        this.state.currentCardIndex = index;
        this.speakCurrentCard();
    }

    changeCategory(category) {
        this.state.selectedCategory = category;
        this.state.cards = this.state.allData[category] || [];
        this.state.currentCardIndex = 0;
        this.speakCurrentCard();
    }

    toggleSidebar() {
        this.state.sidebarExpanded = !this.state.sidebarExpanded;
    }

    toggleVoice() {
        this.state.voiceEnabled = !this.state.voiceEnabled;
        if (!this.state.voiceEnabled) {
            this.narrator.stop();
        } else {
            this.speakCurrentCard();
        }
    }

    speakCurrentCard() {
        if (this.state.voiceEnabled && this.state.cards.length > 0) {
            const card = this.state.cards[this.state.currentCardIndex];
            if (card) this.narrator.speak(card);
        }
    }

    get currentCard() {
        return this.state.cards[this.state.currentCardIndex] || null;
    }

    closeDashboard() {
        this.narrator.stop();
        // Navigate to the Assets list view
        this.actionService.doAction("assetz.assetz_asset_action", {
            clearBreadcrumbs: true,
        });
    }

    onDotClick(index) {
        this.goToCard(index);
    }
}

// Register as a client action
registry.category("actions").add("assetz_dashboard", AssetzDashboard);
