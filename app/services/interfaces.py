import ipaddress
import json
import platform
import subprocess


def get_interfaces() -> list[dict]:
    if platform.system() != "Windows":
        raise NotImplementedError(
            "Interface discovery currently supports Windows only"
        )

    script = r"""
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

    $items = @(
        foreach ($config in Get-NetIPConfiguration) {
            $adapter = Get-NetAdapter -IncludeHidden |
                Where-Object {
                    $_.InterfaceIndex -eq $config.InterfaceIndex
                } | Select-Object -First 1

            foreach ($address in $config.IPv4Address) {
                [PSCustomObject]@{
                    name = $config.InterfaceAlias
                    index = $config.InterfaceIndex
                    ip = $address.IPAddress
                    prefix = $address.PrefixLength
                    gateway = @(
                        $config.IPv4DefaultGateway |
                        ForEach-Object { $_.NextHop }
                    ) | Select-Object -First 1
                    mac = $adapter.MacAddress
                    status = [string]$adapter.Status
                    physical = [bool]$adapter.HardwareInterface
                    description = $adapter.InterfaceDescription
                }
            }
        }
    )

    ConvertTo-Json -InputObject $items -Depth 3 -Compress
    """

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script
        ],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
        check=True
    )

    interfaces = json.loads(result.stdout)

    for interface in interfaces:
        if not isinstance(interface.get("gateway"), str):
            interface["gateway"] = None
        address = ipaddress.IPv4Interface(
            f"{interface['ip']}/{interface['prefix']}"
        )

        interface["network"] = str(address.network)
        interface["netmask"] = str(address.netmask)

        mac = interface.get("mac")

        interface["mac"] = (
            mac.replace("-", ":").upper()
            if mac else None
        )

        interface["recommended"] = (
            interface["status"] == "Up"
            and interface["physical"]
            and not address.ip.is_link_local
            and not address.ip.is_loopback
            and not address.ip.is_unspecified
        )

    return interfaces


def get_recommended_interfaces() -> list[dict]:
    return [
        interface
        for interface in get_interfaces()
        if interface["recommended"]
    ]


if __name__ == "__main__":
    interfaces = get_interfaces()

    print(json.dumps(
        interfaces,
        indent=4,
        ensure_ascii=False
    ))
