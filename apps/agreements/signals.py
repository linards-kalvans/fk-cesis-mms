"""Custom signals for the agreements domain."""

import django.dispatch

# Emitted after an agreement transitions to signed. Args: agreement.
agreement_signed = django.dispatch.Signal()
