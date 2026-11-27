from prometheus_client import Counter, Gauge, Histogram


APP_INFO = Gauge(
    "infrapulse_app_info",
    "InfraPulse application information",
    ["version"]
)

APP_INFO.labels(version="0.1.0").set(1)


CHECKS_TOTAL = Counter(
    "infrapulse_checks_total",
    "Total number of monitoring checks",
    ["protocol", "status"]
)


CHECK_DURATION = Histogram(
    "infrapulse_check_duration_seconds",
    "Duration of monitoring checks in seconds",
    ["protocol"],
    buckets=(
        0.001,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        15.0
    )
)


DEVICES_TOTAL = Gauge(
    "infrapulse_devices_total",
    "Number of registered devices"
)


SERVICES_TOTAL = Gauge(
    "infrapulse_services_total",
    "Number of registered services"
)


OPEN_INCIDENTS = Gauge(
    "infrapulse_open_incidents",
    "Number of currently open incidents",
    ["type"]
)


INCIDENT_EVENTS = Counter(
    "infrapulse_incident_events_total",
    "Total number of incident events",
    ["type", "event"]
)


MONITORING_CYCLES = Counter(
    "infrapulse_monitoring_cycles_total",
    "Total number of monitoring cycles",
    ["status"]
)


MONITORING_CYCLE_DURATION = Histogram(
    "infrapulse_monitoring_cycle_duration_seconds",
    "Duration of monitoring cycles in seconds"
)
def record_check(
    protocol: str,
    status: str,
    duration: float
):
    CHECKS_TOTAL.labels(
        protocol=protocol,
        status=status
    ).inc()

    CHECK_DURATION.labels(
        protocol=protocol
    ).observe(duration)


def record_incident(
    incident_type: str,
    event: str
):
    INCIDENT_EVENTS.labels(
        type=incident_type,
        event=event
    ).inc()


def record_monitoring_cycle(
    status: str,
    duration: float
):
    MONITORING_CYCLES.labels(
        status=status
    ).inc()

    MONITORING_CYCLE_DURATION.observe(
        duration
    )
