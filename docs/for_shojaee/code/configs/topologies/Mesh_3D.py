# Mesh_3D.py - 3D Mesh Topology with TSV Support for gem5
# This file should be placed in: gem5/configs/topologies/Mesh_3D.py
#
# Usage:
#   --topology=Mesh_3D --mesh-rows=4 --mesh-cols=4 --mesh-layers=4 --tsv-latency=2
#
# Note: m5.objects and m5.params are gem5-specific modules only available
# when running inside gem5. The linter cannot resolve these imports, but
# they are valid in the gem5 runtime environment.
# type: ignore

from m5.objects import *  # noqa: F403, F401, F405
from m5.params import *  # noqa: F403, F401, F405
from topologies.BaseTopology import SimpleTopology


# [فارسی] -------------------------------------------------------------------
# این فایل توپولوژیِ شبکهٔ سه‌بعدی (Mesh_3D) را می‌سازد: روترها را در یک شبکهٔ
# rows×cols×layers می‌چیند و آن‌ها را با لینک‌های افقی (شرق/غرب، شمال/جنوب) و
# لینک‌های عمودیِ TSV (بالا/پایین) به هم وصل می‌کند. الگوریتم‌های سه‌بعدی
# (XYZ, DeepNR3D, Proposed) روی همین توپولوژی اجرا می‌شوند.
# --------------------------------------------------------------------------
class Mesh_3D(SimpleTopology):
    description = "Mesh_3D"

    # [فارسی] constructor: فقط فهرستِ گره‌ها (کنترلرها) را نگه می‌دارد.
    def __init__(self, controllers):
        self.nodes = controllers

    # [فارسی] makeTopology: تابعِ اصلی که gem5 صدا می‌زند تا روترها و لینک‌ها را بسازد.
    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        nodes = self.nodes

        # Get topology parameters from options
        num_rows = options.mesh_rows
        num_cols = getattr(options, "mesh_cols", None)
        if num_cols is None:
            # If mesh_cols not specified, calculate from num_cpus and mesh_rows
            num_cols = options.num_cpus // num_rows
        num_layers = getattr(options, "mesh_layers", 1)  # Default to 1 if not set
        tsv_latency = getattr(
            options, "tsv_latency", 2
        )  # Default TSV latency = 2 cycles

        # Calculate total number of routers
        # Router ID = z * (rows * cols) + y * cols + x
        # [فارسی] تعدادِ کلِ روترها = سطر × ستون × لایه. همان فرمولِ شمارهٔ روتر که
        # در همهٔ توابعِ مسیریابیِ ++C هم استفاده می‌شود (مهم: همه‌جا یکسان بماند).
        num_routers = num_rows * num_cols * num_layers

        # Default values for link latency and router latency
        link_latency = options.link_latency
        router_latency = options.router_latency

        # There must be an evenly divisible number of cntrls to routers
        # Also, obviously the number of routers must be <= the number of nodes
        cntrls_per_router, remainder = divmod(len(nodes), num_routers)
        assert num_routers > 0 and num_routers <= len(nodes), (
            f"Number of routers ({num_routers}) must be <= number of nodes ({len(nodes)})"
        )

        # Create the routers in the 3D mesh
        routers = [
            Router(router_id=i, latency=router_latency) for i in range(num_routers)
        ]
        network.routers = routers
        network.num_rows = num_rows
        network.num_layers = num_layers

        # Link counter to set unique link ids
        link_count = 0

        # Add all but the remainder nodes to the list of nodes to be uniformly
        # distributed across the network.
        network_nodes = []
        remainder_nodes = []
        for node_index in range(len(nodes)):
            if node_index < (len(nodes) - remainder):
                network_nodes.append(nodes[node_index])
            else:
                remainder_nodes.append(nodes[node_index])

        # Connect each node to the appropriate router
        ext_links = []
        for i, n in enumerate(network_nodes):
            cntrl_level, router_id = divmod(i, num_routers)
            assert cntrl_level < cntrls_per_router
            ext_links.append(
                ExtLink(
                    link_id=link_count,
                    ext_node=n,
                    int_node=routers[router_id],
                    latency=link_latency,
                )
            )
            link_count += 1

        # Connect the remaining nodes to router 0 (DMA, ROM-dir, or other extra nodes).
        for i, node in enumerate(remainder_nodes):
            assert i < remainder
            ext_links.append(
                ExtLink(
                    link_id=link_count,
                    ext_node=node,
                    int_node=routers[0],
                    latency=link_latency,
                )
            )
            link_count += 1

        network.ext_links = ext_links

        # Create the 3D mesh links
        int_links = []

        # [فارسی] get_router_id: مختصاتِ (x, y, z) را به شمارهٔ خطیِ روتر تبدیل می‌کند.
        # دقیقاً معکوسِ همان فرمولی که توابعِ مسیریابی برای استخراجِ مختصات به کار می‌برند.
        def get_router_id(x, y, z):
            """Convert 3D coordinates (x, y, z) to router ID."""
            return z * (num_rows * num_cols) + y * num_cols + x

        # Connect routers in 3D mesh
        for z in range(num_layers):
            for y in range(num_rows):
                for x in range(num_cols):
                    router_id = get_router_id(x, y, z)

                    # Horizontal links in X direction (East-West)
                    if x < num_cols - 1:
                        east_router_id = get_router_id(x + 1, y, z)
                        int_links.append(
                            IntLink(
                                link_id=link_count,
                                src_node=routers[router_id],
                                dst_node=routers[east_router_id],
                                src_outport="East",
                                dst_inport="West",
                                latency=link_latency,
                            )
                        )
                        link_count += 1
                        # Reverse link
                        int_links.append(
                            IntLink(
                                link_id=link_count,
                                src_node=routers[east_router_id],
                                dst_node=routers[router_id],
                                src_outport="West",
                                dst_inport="East",
                                latency=link_latency,
                            )
                        )
                        link_count += 1

                    # Horizontal links in Y direction (North-South)
                    if y < num_rows - 1:
                        south_router_id = get_router_id(x, y + 1, z)
                        int_links.append(
                            IntLink(
                                link_id=link_count,
                                src_node=routers[router_id],
                                dst_node=routers[south_router_id],
                                src_outport="South",
                                dst_inport="North",
                                latency=link_latency,
                            )
                        )
                        link_count += 1
                        # Reverse link
                        int_links.append(
                            IntLink(
                                link_id=link_count,
                                src_node=routers[south_router_id],
                                dst_node=routers[router_id],
                                src_outport="North",
                                dst_inport="South",
                                latency=link_latency,
                            )
                        )
                        link_count += 1

                    # TSV links in Z direction (Up-Down) - vertical interconnects
                    # [فارسی] لینک‌های عمودیِ TSV بینِ لایه‌ها. توجه: تأخیرِ این‌ها
                    # (tsv_latency) از لینک‌های افقی بیشتر است (معمولاً ۲ تا ۳ سیکل)،
                    # چون عبور از لایه‌ها هزینهٔ فیزیکیِ بیشتری دارد.
                    if z < num_layers - 1:
                        up_router_id = get_router_id(x, y, z + 1)
                        int_links.append(
                            IntLink(
                                link_id=link_count,
                                src_node=routers[router_id],
                                dst_node=routers[up_router_id],
                                src_outport="Up",
                                dst_inport="Down",
                                latency=tsv_latency,  # TSV latency (typically 2-3 cycles)
                            )
                        )
                        link_count += 1
                        # Reverse link
                        int_links.append(
                            IntLink(
                                link_id=link_count,
                                src_node=routers[up_router_id],
                                dst_node=routers[router_id],
                                src_outport="Down",
                                dst_inport="Up",
                                latency=tsv_latency,
                            )
                        )
                        link_count += 1

        network.int_links = int_links

        return (routers, int_links, ext_links)
