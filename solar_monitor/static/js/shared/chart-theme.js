// Shared Chart.js look for every page, so charts match the rest of the UI
// instead of falling back to Chart.js's built-in font and tooltip style.
// Must load AFTER chart.umd.js and BEFORE any chart is created.

Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
Chart.defaults.color = "#8c8ca0";
Chart.defaults.borderColor = "#2a2a38";

// Hover anywhere along the x-axis, not only exactly on a point/bar.
Chart.defaults.interaction.mode = "index";
Chart.defaults.interaction.intersect = false;

const tooltip = Chart.defaults.plugins.tooltip;
tooltip.backgroundColor = "#22222e";
tooltip.borderColor = "#34344a";
tooltip.borderWidth = 1;
tooltip.titleColor = "#f1f1f5";
tooltip.bodyColor = "#f1f1f5";
tooltip.padding = 10;
tooltip.cornerRadius = 10;
tooltip.usePointStyle = true;
tooltip.boxPadding = 4;
