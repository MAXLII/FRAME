from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.services.ethernet_discovery import EthernetDiscoveryDevice, EthernetDiscoveryScan


class EthernetDiscoveryDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        translate: Callable[[str], str],
        on_search: Callable[[], None],
        on_device_selected: Callable[[EthernetDiscoveryDevice, bool], None],
    ) -> None:
        super().__init__(parent)
        self.translate = translate
        self.on_search = on_search
        self.on_device_selected = on_device_selected
        self.devices_by_item: dict[str, EthernetDiscoveryDevice] = {}
        self.items_by_identity: dict[str, str] = {}
        self.online_items: set[str] = set()
        self.status_var = tk.StringVar(value=self.translate("Waiting to search for Ethernet devices."))
        self.details_var = tk.StringVar(value=self.translate("Select a device to fill Host and TCP Port."))

        self.title(self.translate("Ethernet Device Discovery"))
        self.geometry("1040x430")
        self.minsize(820, 340)
        self.transient(parent)

        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)

        ttk.Label(root, textvariable=self.status_var).grid(row=0, column=0, sticky="w", pady=(0, 10))

        columns = ("status", "name", "ip", "mac", "port", "firmware", "protocol", "interface")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", selectmode="browse")
        headings = {
            "status": self.translate("Status"),
            "name": self.translate("Device Name"),
            "ip": self.translate("IP Address"),
            "port": self.translate("TCP Port"),
            "mac": self.translate("MAC Address"),
            "firmware": self.translate("Firmware Version"),
            "protocol": self.translate("FRAME Protocol"),
            "interface": self.translate("Local Interface"),
        }
        widths = {
            "status": 75,
            "name": 160,
            "ip": 120,
            "port": 75,
            "mac": 145,
            "firmware": 115,
            "protocol": 105,
            "interface": 210,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=65, stretch=column in {"name", "interface"})
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection)
        self.tree.bind("<Double-1>", self._connect_selected)

        ttk.Label(root, textvariable=self.details_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 8))

        buttons = ttk.Frame(root)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        self.search_button = ttk.Button(buttons, text=self.translate("Search Again"), command=self.on_search)
        self.search_button.grid(row=0, column=1, padx=(0, 8))
        self.connect_button = ttk.Button(
            buttons,
            text=self.translate("Connect Selected Device"),
            command=self._connect_selected,
            style="Accent.TButton",
        )
        self.connect_button.grid(row=0, column=2, padx=(0, 8))
        self.connect_button.state(["disabled"])
        ttk.Button(buttons, text=self.translate("Close"), command=self.destroy).grid(row=0, column=3)

    def set_searching(self) -> None:
        self.online_items.clear()
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            if values:
                values[0] = self.translate("Searching")
                self.tree.item(item, values=values)
        self.status_var.set(self.translate("Searching Ethernet devices for 400 ms..."))
        self.details_var.set(self.translate("Manual Host and TCP Port entry remains available in the main window."))
        self.search_button.state(["disabled"])
        self.connect_button.state(["disabled"])

    def set_results(self, scan: EthernetDiscoveryScan) -> None:
        self.search_button.state(["!disabled"])
        self.online_items.clear()
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            if values:
                values[0] = self.translate("Offline")
                self.tree.item(item, values=values)
        for device in scan.devices:
            values = (
                self.translate("Online"),
                device.name,
                device.ip_address,
                device.mac_address,
                device.tcp_port,
                device.firmware_version,
                device.frame_protocol_version,
                f"{device.interface.name} ({device.interface.address})",
            )
            item = self.items_by_identity.get(device.identity)
            if item is None or not self.tree.exists(item):
                item = self.tree.insert("", "end", values=values)
                self.items_by_identity[device.identity] = item
            else:
                self.tree.item(item, values=values)
            self.devices_by_item[item] = device
            self.online_items.add(item)
        selection = self.tree.selection()
        if selection and selection[0] in self.online_items:
            self.connect_button.state(["!disabled"])
        else:
            self.connect_button.state(["disabled"])
            if selection:
                self.details_var.set(self.translate("The selected device did not reply to the latest search."))
        elapsed_ms = round(scan.duration_seconds * 1000)
        if scan.devices:
            self.status_var.set(
                self.translate("Found {device_count} device(s) through {interface_count} IPv4 interface(s) in {elapsed_ms} ms.").format(
                    device_count=len(scan.devices),
                    interface_count=len(scan.interfaces),
                    elapsed_ms=elapsed_ms,
                )
            )
            self.details_var.set(self.translate("Select a device to fill Host and TCP Port."))
            return
        if not scan.interfaces:
            self.status_var.set(self.translate("No active IPv4 interface is available. Enter Host and TCP Port manually."))
        else:
            self.status_var.set(
                self.translate("No device replied in {elapsed_ms} ms. Check subnet, VLAN and firewall, or enter Host manually.").format(
                    elapsed_ms=elapsed_ms,
                )
            )
        self.details_var.set(self.translate("Manual Host and TCP Port entry remains available in the main window."))

    def set_error(self, message: str) -> None:
        self.search_button.state(["!disabled"])
        self.connect_button.state(["disabled"])
        self.online_items.clear()
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            if values:
                values[0] = self.translate("Offline")
                self.tree.item(item, values=values)
        self.status_var.set(self.translate("Ethernet discovery failed: {message}").format(message=message))
        self.details_var.set(self.translate("Manual Host and TCP Port entry remains available in the main window."))

    def _on_tree_selection(self, _event=None) -> None:
        self._apply_selection(connect=False)

    def _connect_selected(self, _event=None) -> None:
        self._apply_selection(connect=True)

    def _apply_selection(self, *, connect: bool) -> None:
        selection = self.tree.selection()
        if not selection:
            self.connect_button.state(["disabled"])
            return
        device = self.devices_by_item.get(selection[0])
        if device is None or selection[0] not in self.online_items:
            self.connect_button.state(["disabled"])
            self.details_var.set(self.translate("The selected device did not reply to the latest search."))
            return
        self.connect_button.state(["!disabled"])
        self.details_var.set(
            f"{device.name} | {device.ip_address}:{device.tcp_port} | "
            f"MAC {device.mac_address} | FW {device.firmware_version} | FRAME {device.frame_protocol_version}"
        )
        self.on_device_selected(device, connect)
        if connect:
            self.destroy()
