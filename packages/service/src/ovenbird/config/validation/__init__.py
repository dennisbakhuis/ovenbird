"""Validation of the settings, one module per feature.

Field rules (curve, quiet windows, notifications, Home Assistant, access) are called
by the :class:`~ovenbird.config.settings.Settings` validators; the cross-field rules
are gathered by :func:`ovenbird.config.validation.issues.control_issues`. The
wood-stove rules live with the feature, in :mod:`ovenbird.stove.validation`.
"""
