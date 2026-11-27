from app.services.telegram import send_message


def notify_incident(
    event: str,
    device_id: int,
    ip_address: str
) -> bool:

    if event == "opened":

        message = (
            "🔴 INCIDENT DETECTED\n\n"
            f"Device ID: {device_id}\n"
            f"IP: {ip_address}\n"
            "Status: No ICMP response\n"
            "Source: InfraPulse Monitoring"
        )

    elif event == "resolved":

        message = (
            "🟢 INCIDENT RESOLVED\n\n"
            f"Device ID: {device_id}\n"
            f"IP: {ip_address}\n"
            "Status: Online\n"
            "Source: InfraPulse Monitoring"
        )

    else:
        return False

    return send_message(message)
def notify_service_incident(
    event: str,
    service_id: int,
    name: str,
    protocol: str,
    target: str,
    status: str
) -> bool:

    if event == "opened":
        title = "🔴 SERVICE INCIDENT DETECTED"

    elif event == "resolved":
        title = "🟢 SERVICE INCIDENT RESOLVED"

    else:
        return False

    message = (
        f"{title}\n\n"
        f"Service: {name}\n"
        f"Service ID: {service_id}\n"
        f"Protocol: {protocol.upper()}\n"
        f"Target: {target}\n"
        f"Status: {status}\n"
        "Source: InfraPulse Monitoring"
    )

    return send_message(message)