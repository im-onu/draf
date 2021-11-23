import logging
from collections import OrderedDict
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import pandas as pd
import plotly as py
import plotly.figure_factory as ff
import plotly.graph_objs as go
import seaborn as sns
from IPython.display import display
from ipywidgets import interact, widgets
from pandas.io.formats.style import Styler as pdStyler

from draf import helper as hp
from draf.plotting.base_plotter import BasePlotter
from draf.plotting.scen_plotting import COLORS, ScenPlotter

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARN)

NAN_REPRESENTATION = "-"


class CsPlotter(BasePlotter):
    """Plotter for case studies.

    Args:
        cs: The CaseStudy object, containing all scenarios.
    """

    def __init__(self, cs: "CaseStudy"):
        self.figsize = (16, 4)
        self.cs = cs
        self.notebook_mode: bool = self.script_type() == "jupyter"
        self.optimize_layout_for_reveal_slides = False

    def __getstate__(self):
        """For serialization with pickle."""
        return None

    def tables(self):
        cs = self.cs
        funcs = {
            "1D params ": ("p_table", "table fa-lg"),
            "1D variables ": ("v_table", "table fa-lg"),
            "Investments ": ("invest_table", "money fa-lg"),
            "Capacities ": ("capa_table", " fa-cubes fa-lg"),
            "Yields ": ("yields_table", " fa-eur fa-lg"),
            "eGrid ": ("eGrid_table", " fa-plug fa-lg"),
            "Pareto ": ("pareto_table", " fa-arrows-h fa-lg"),
            "BES ": ("bes_table", "fa-solid fa-battery-half fa-lg"),
            "Time ": ("time_table", " fa-clock-o fa-lg"),
        }
        ui = widgets.ToggleButtons(
            options={k: v[0] for k, v in funcs.items()},
            description="Table:",
            icons=[v[1] for v in funcs.values()],
            # for icons see https://fontawesome.com/v4.7/icons/
        )

        @interact(table=ui, gradient=False)
        def f(table, gradient):
            kw = dict()
            if table in ("p_table", "v_table"):
                what, func = table.split("_")
                kw.update(what=what)
            else:
                func = table
            kw.update(gradient=gradient)
            display(getattr(cs.plot, func)(**kw))

    def pareto_table(self, gradient: bool = False) -> pdStyler:
        cs = self.cs
        df = cs.pareto
        styled_df = df.style.set_table_styles(get_leftAlignedIndex_style()).format(
            {v: "{:,.0f} " + f"{cs.REF_scen.get_unit(v)}" for v in cs.obj_vars}
        )

        if gradient:
            styled_df = styled_df.background_gradient(cmap="OrRd")
        return styled_df

    def yields_table(self, gradient: bool = False) -> pdStyler:
        """Returns a styled pandas table with cost and carbon savings, and avoidance cost."""
        cs = self.cs

        savings = cs.pareto.iloc[0] - cs.pareto

        rel_savings = savings / cs.pareto.iloc[0]

        avoid_cost = -savings["C_TOT_"] / savings["CE_TOT_"] * 1e6  # in k€/kgCO2eq  # in €/tCO2eq

        df = pd.DataFrame(
            {
                ("Absolute", "Costs"): cs.pareto["C_TOT_"],
                ("Absolute", "Emissions"): cs.pareto["CE_TOT_"] / 1e3,
                ("Abolute savings", "Costs"): savings["C_TOT_"],
                ("Abolute savings", "Emissions"): savings["CE_TOT_"] / 1e3,
                ("Relative savings", "Costs"): rel_savings["C_TOT_"],
                ("Relative savings", "Emissions"): rel_savings["CE_TOT_"],
                ("Annual costs", "C_invAnn"): pd.Series(cs.get_ent("C_TOT_invAnn_")),
                ("Annual costs", "C_op"): pd.Series(cs.get_ent("C_TOT_op_")),
                ("", "Emission avoidance costs"): avoid_cost,
                ("", "C_inv"): pd.Series(cs.get_ent("C_TOT_inv_")),
            }
        )
        df[("", "Payback time")] = df[("", "C_inv")] / (
            df[("Annual costs", "C_op")].iloc[0] - df[("Annual costs", "C_op")]
        )

        def color_negative_red(val):
            color = "red" if val < 0 else "black"
            return f"color: {color}"

        df = df.fillna(0)

        if gradient:
            styled_df = (
                df.style.background_gradient(subset=["Absolute"], cmap="Greens")
                .background_gradient(subset=["Abolute savings"], cmap="Reds")
                .background_gradient(subset=["Relative savings"], cmap="Blues")
                .background_gradient(subset=["Annual costs"], cmap="Purples")
                .background_gradient(subset=[""], cmap="Greys")
            )

        else:
            styled_df = df.style.applymap(color_negative_red)

        return styled_df.format(
            {
                ("Absolute", "Costs"): "{:,.0f} k€",
                ("Absolute", "Emissions"): "{:,.0f} t",
                ("Abolute savings", "Costs"): "{:,.0f} k€",
                ("Abolute savings", "Emissions"): "{:,.0f} t",
                ("Relative savings", "Costs"): "{:,.2%}",
                ("Relative savings", "Emissions"): "{:,.2%}",
                ("", "Emission avoidance costs"): "{:,.0f} €/t",
                ("", "C_inv"): "{:,.0f} k€",
                ("Annual costs", "C_invAnn"): "{:,.0f} k€/a",
                ("Annual costs", "C_op"): "{:,.0f} k€/a",
                ("", "Payback time"): "{:,.1f} a",
            }
        ).set_table_styles(get_leftAlignedIndex_style() + get_multiColumnHeader_style(df))

    def bes_table(self, gradient: bool = False) -> pdStyler:
        cs = self.cs
        df = pd.DataFrame(index=cs.scens_ids)
        df["CAPn"] = [sc.res.E_BES_CAPn_ for sc in cs.scens_list]
        df["W_out"] = [sc.gte(sc.res.P_BES_out_T) / 1e3 for sc in cs.scens_list]
        df["Charging_cycles"] = df["W_out"] / (df["CAPn"] / 1e3)
        styled_df = df.style.format(
            {"CAPn": "{:,.0f} kWh", "W_out": "{:,.0f} MWh/a", "Charging_cycles": "{:,.0f}"}
        )
        if gradient:
            styled_df = styled_df.background_gradient(cmap="OrRd")
        return styled_df

    def eGrid_table(self, gradient: bool = False, pv: bool = False) -> pdStyler:
        cs = self.cs
        df = pd.DataFrame(index=cs.scens_ids)
        df["P_max"] = [sc.res.P_EG_buyPeak_ for sc in cs.scens_list]
        df["P_max_reduction"] = df["P_max"].iloc[0] - df["P_max"]
        df["P_max_reduction_rel"] = df["P_max_reduction"] / df["P_max"].iloc[0]
        df["t_use"] = [sc.get_EG_full_load_hours() for sc in cs.scens_list]
        df["W_buy"] = [sc.gte(sc.res.P_EG_buy_T) / 1e6 for sc in cs.scens_list]
        df["W_sell"] = [sc.gte(sc.res.P_EG_sell_T) / 1e6 for sc in cs.scens_list]
        if pv:
            df["W_pv_own"] = [sc.gte(sc.res.P_PV_OC_T) / 1e3 for sc in cs.scens_list]
        styled_df = df.style.format(
            {
                "P_max": "{:,.0f} kW",
                "P_max_reduction": "{:,.0f} kW",
                "P_max_reduction_rel": "{:,.1%}",
                "t_use": "{:,.0f} h",
                "W_buy": "{:,.2f} GWh/a",
                "W_sell": "{:,.2f} GWh/a",
                "W_pv_own": "{:,.2f} MWh/a",
            }
        ).set_table_styles(get_leftAlignedIndex_style())
        if gradient:
            styled_df = styled_df.background_gradient(cmap="OrRd")
        return styled_df

    def pareto(
        self,
        use_plotly: bool = True,
        target_c_unit: Optional[str] = None,
        target_ce_unit: Optional[str] = None,
        c_dict: Dict = None,
        label_verbosity: int = 1,
        do_title: bool = True,
    ) -> go.Figure:
        """Plots the Pareto points in an scatter plot.

        Args:
            use_plotly: If True, Plotly is used, else Matplotlib
            target_c_unit: The unit of the cost.
            target_ce_unit: The unit of the carbon emissions.
            c_dict: colors the Pareto points according to key-strings in their scenario doc
                e.g. {"FLAT": "green", "TOU": "blue", "RTP": "red"}
            label_verbosity: Choose between 1: "id", 2: "name", 3: "doc".
            do_title: If title is shown.
        """
        cs = self.cs
        pareto = cs.pareto.copy()
        scens_list = cs.scens_list

        options = {1: "id", 2: "name", 3: "doc"}
        pareto.index = [getattr(sc, options[label_verbosity]) for sc in scens_list]

        units = dict()
        for x, target_unit in zip(["C_TOT_", "CE_TOT_"], [target_c_unit, target_ce_unit]):
            pareto[x], units[x] = hp.auto_fmt(
                pareto[x], scens_list[0].get_unit(x), target_unit=target_unit
            )

        def get_colors(c_dict: Dict) -> List:
            return [c for sc in scens_list for i, c in c_dict.items() if i in sc.doc]

        colors = "black" if c_dict is None else get_colors(c_dict)
        ylabel = f"Annualized costs [{units['C_TOT_']}]"
        xlabel = f"Carbon emissions [{units['CE_TOT_']}]"

        if use_plotly:
            hwr_ = "<b>id:</b> {}<br><b>name:</b> {}<br><b>doc:</b> {}<br>"

            trace = go.Scatter(
                x=pareto["CE_TOT_"],
                y=pareto["C_TOT_"],
                mode="markers+text",
                text=list(pareto.index) if label_verbosity else None,
                hovertext=[hwr_.format(sc.id, sc.name, sc.doc) for sc in scens_list],
                textposition="bottom center",
                marker=dict(size=12, color=colors, showscale=False),
            )
            data = [trace]
            layout = go.Layout(
                hovermode="closest",
                title=get_pareto_title(pareto, units).replace("\n", "<br>") if do_title else "",
                xaxis=dict(title=xlabel),
                yaxis=dict(title=ylabel),
                margin=dict(l=5, r=5, b=5),
            )

            if self.optimize_layout_for_reveal_slides:
                layout = hp.optimize_plotly_layout_for_reveal_slides(layout)

            fig = go.Figure(data=data, layout=layout)
            return fig

        else:
            fig, ax = plt.subplots(figsize=self.figsize)
            pareto.plot.scatter("CE_TOT_", "C_TOT_", s=30, marker="o", ax=ax, color=colors)
            ax.set(ylabel=ylabel, xlabel=xlabel)
            if do_title:
                ax.set(title=get_pareto_title(pareto, units))
            for sc_name in list(pareto.index):
                ax.annotate(
                    s=sc_name,
                    xy=(pareto["CE_TOT_"][sc_name], pareto["C_TOT_"][sc_name]),
                    rotation=45,
                    ha="left",
                    va="bottom",
                )
            return fig

    def pareto_curves(
        self,
        groups: List[str] = None,
        c_unit: Optional[str] = None,
        ce_unit: Optional[str] = None,
        c_dict: Optional[Dict] = None,
        label_verbosity: int = 0,
        do_title: bool = True,
    ) -> go.Figure:
        """EXPERIMENTAL: Plot based on pareto() considering multiple pareto curve-groups."""

        def get_hover_text(sc, ref_scen):
            sav_C = ref_scen.res.C_TOT_ - sc.res.C_TOT_
            sav_C_fmted, unit_C = hp.auto_fmt(sav_C, sc.get_unit("C_TOT_"))
            sav_C_rel = sav_C / ref_scen.res.C_TOT_
            sav_CE = ref_scen.res.CE_TOT_ - sc.res.CE_TOT_
            sav_CE_fmted, unit_CE = hp.auto_fmt(sav_CE, sc.get_unit("CE_TOT_"))
            sav_CE_rel = sav_CE / ref_scen.res.CE_TOT_

            return "<br>".join(
                [
                    f"<b>Id:</b> {sc.id}",
                    f"<b>Name:</b> {sc.name}",
                    f"<b>Doc:</b> {sc.doc}",
                    f"<b>Cost savings:</b> {sav_C_fmted:.2f} {unit_C} ({sav_C_rel:.3%})",
                    f"<b>Emission savings:</b> {sav_CE_fmted:.2f} {unit_CE} ({sav_CE_rel:.3%})",
                ]
            )

        def get_text(sc, label_verbosity) -> str:
            if label_verbosity == 1:
                return sc.id
            elif label_verbosity == 2:
                return sc.name
            elif label_verbosity == 3:
                return sc.doc
            elif label_verbosity == 4:
                return f"α={sc.params.k_PTO_alpha_:.2f}"

        cs = self.cs
        pareto = cs.pareto.copy()
        scens = cs.scens_list

        colors = [
            "#606269",  # some grey for REF
            # "#F26535",  # for FLAT
            # "#FCC706",   # for TOU
            # "#9BAF65",   # for RTP
            "#1f77b4",  # (plotly default) muted blue
            "#ff7f0e",  # (plotly default) safety orange
            "#2ca02c",  # (plotly default) cooked asparagus green
            "#d62728",  # (plotly default) brick red
            "#9467bd",  # (plotly default) muted purple
            "#8c564b",  # (plotly default) chestnut brown
            "#e377c2",  # (plotly default) raspberry yogurt pink
            "#7f7f7f",  # (plotly default) middle gray
            "#bcbd22",  # (plotly default) curry yellow-green
            "#17becf",  # (plotly default) blue-teal
        ]

        if isinstance(groups, list) and c_dict is None:
            c_dict = {g: colors[i] for i, g in enumerate(groups)}

        if c_dict is None and groups is None:
            c_dict = {"": "black"}
            c_dict = dict(REF="#606269", FLAT="#F26535", TOU="#FCC706", RTP="#9BAF65")

        if pareto.empty:
            logger.warning("\nPareto-Dataframe is empty!")
            return

        pareto["C_TOT_"], c_unit = hp.auto_fmt(
            pareto["C_TOT_"], scens[0].get_unit("C_TOT_"), target_unit=c_unit
        )
        pareto["CE_TOT_"], ce_unit = hp.auto_fmt(
            pareto["CE_TOT_"], scens[0].get_unit("CE_TOT_"), target_unit=ce_unit
        )
        title = ""

        layout = go.Layout(
            hovermode="closest",
            title=title if do_title else "",
            xaxis=dict(title=f"Carbon emissions [{ce_unit}]"),
            yaxis=dict(title=f"Costs [{c_unit}]"),
        )

        if self.optimize_layout_for_reveal_slides:
            layout = hp.optimize_plotly_layout_for_reveal_slides(layout)

        data = []
        for ix, c in c_dict.items():
            scens_ = [sc for sc in scens if ix in sc.name]
            pareto_ = [getattr(cs.scens, ix) for ix in pareto.index]

            trace = go.Scatter(
                x=[pareto.loc[sc.id, "CE_TOT_"] for sc in scens_],
                y=[pareto.loc[sc.id, "C_TOT_"] for sc in scens_],
                mode="lines+markers+text" if bool(label_verbosity) else "lines+markers",
                text=[get_text(sc, label_verbosity) for sc in scens_]
                if bool(label_verbosity)
                else None,
                hovertext=[get_hover_text(sc, ref_scen=cs.REF_scen) for sc in scens_],
                textposition="bottom center",
                marker=dict(size=12, color=c, showscale=False),
                name=ix,
            )
            data.append(trace)

        fig = go.Figure(layout=layout, data=data)

        if not self.notebook_mode:
            fp = str(cs._res_fp / "plotly_pareto_scatter.html")
            py.offline.plot(fig, filename=fp)

        return fig

    def heatmap_interact(
        self,
        what: str = "p",
        dim: str = "T",
        select: Tuple[Union[int, str]] = None,
        cmap: str = "OrRd",
        show_info: bool = True,
    ) -> go.Figure:
        """Returns an interactive heatmap widget that enables browsing through time series.

        Args:
            what: Selects between Variables ('v') and Parameters ('p').
            dim: Dimensions to filter.
            select: Tuple of indexers for data with additional dimension(s) besides the time.
            cmap: Color scale.
            show_info: If additional information such as Scenario, Entity, Stats are displayed.
        """
        cs = self.cs
        sc = cs.any_scen
        layout = go.Layout(
            title=None,
            xaxis=dict(title=f"Days of year {cs.year}"),
            yaxis=dict(title="Time of day"),
            margin=dict(b=5, l=5, r=5),
        )
        fig = go.FigureWidget(layout=layout)
        heatmap = fig.add_heatmap(colorscale=cmap)

        @interact(scen_id=cs.scens_ids, ent=sc.get_var_par_dic(what)[dim].keys())
        def update(scen_id, ent):
            with fig.batch_update():
                sc = getattr(cs.scens, scen_id)
                ser = sc.get_var_par_dic(what)[dim][ent]
                title_addon_if_select = ""

                if len(dim) > 1:
                    if select is None:
                        ser = ser.sum(level=0)
                    else:
                        indexer = select if isinstance(select, Tuple) else (select,)
                        ser = ser.loc[(slice(None, None),) + indexer]
                        s = ", ".join([f"{k}={v}" for k, v in zip(dim[1:], indexer)])
                        title_addon_if_select = f"[{s}]"

                data = ser.values.reshape((cs.steps_per_day, -1), order="F")[:, :]
                idx = cs.dated(ser).index
                heatmap.data[0].x = pd.date_range(start=idx[0], end=idx[-1], freq="D")
                heatmap.data[0].y = pd.date_range(
                    start="0:00", freq=cs.freq, periods=cs.steps_per_day
                )
                heatmap.data[0].z = data
                heatmap.layout.yaxis.tickformat = "%H:%M"
                if show_info:
                    unit = "-" if sc.get_unit(ent) == "" else sc.get_unit(ent)
                    heatmap.layout.title = (
                        "<span style='font-size:medium;'>"
                        f"{grey('Scenario:')} <b>{scen_id}</b> ◦ {sc.doc}"
                        f"<br>{grey(' ⤷ Entity:')} <b>{ent}</b>{title_addon_if_select} ◦ {sc.get_doc(ent)}"
                        f"<br>{grey('    ⤷ Stats:')} ∑ <b>{data.sum():,.2f}</b> ◦ Ø <b>{data.mean():,.2f}</b>"
                        f" ◦ min <b>{data.min():,.2f}</b> ◦ max <b>{data.max():,.2f}</b>"
                        f"  [<b>{unit}</b>]"
                        "</span>"
                    )

        return fig

    def sankey(self) -> go.Figure:
        @interact(sc=self.cs.scens_dic)
        def f(sc):
            display(sc.plot.sankey())

    def sankey_interact(self, string_builder_func: Optional[Callable] = None) -> go.Figure:
        """Returns an interactive Sankey plot widget to browse scenarios.

        Args:
            string_builder_func: Function that returns a space-seperated table with
                the columns type, source, targe, value. e.g.
                ```
                type source target value
                F GAS CHP 1000
                E CHP EG 450
                ```
        """
        cs = self.cs

        data = dict(
            type="sankey",
            node=dict(
                pad=10,
                thickness=10,
                line=dict(color="white", width=0),
                color="hsla(0, 0%, 0%, 0.5)",
            ),
        )

        layout = dict(title=None, font=dict(size=14), margin=dict(t=5, b=5, l=5, r=5))

        fig = go.FigureWidget(data=[data], layout=layout)
        sankey = fig.add_sankey()

        sankeys_dic = {}

        for scen_name, sc in cs.valid_scens.items():
            df = sc.plot._get_sankey_df(string_builder_func)
            source_s, target_s, value = (list(df[s]) for s in ["source", "target", "value"])

            label = list(set(source_s + target_s))
            source = [label.index(x) for x in source_s]
            target = [label.index(x) for x in target_s]

            link_color = [COLORS[x] for x in df["type"].values.tolist()]

            sankeys_dic[scen_name] = dict(
                source=source, target=target, value=value, color=link_color
            )

        @interact(scen_name=cs.valid_scens.keys())
        def update(scen_name):
            with fig.batch_update():
                sankey["data"][0]["link"] = sankeys_dic[scen_name]
                sankey["data"][0]["node"].label = label
                sankey["data"][0]["node"].color = "hsla(0, 0%, 0%, 0.5)"
                sankey["data"][0].orientation = "h"
                sankey["data"][0].valueformat = ".2f"
                sankey["data"][0].valuesuffix = "MWh"

        return fig

    def big_plot(self, string_builder_func, sc: "Scenario" = None, sort: bool = True) -> go.Figure:
        """Experimental: Builds a big plot containing other subplots.

        Args:
            string_builder_func: Function that returns a space-seperated table with
                the columns type, source, targe, value. e.g.
                ```
                type source target value
                F GAS CHP 1000
                E CHP EG 450
                ```
            sc: Scenario object, which is selected.
            sort: If scenarios are sorted by total costs.

        """
        cs = self.cs
        sc = cs.REF_scen if sc is None else sc
        r = sc.res
        p = sc.params

        if not hasattr(cs.REF_scen.res, "C_TOT_op_") or not hasattr(cs.REF_scen.res, "C_TOT_inv_"):
            for scen in cs.scens_list:
                scen.res.C_TOT_op_ = scen.res.C_TOT_
                scen.res.C_TOT_inv_ = 0

        css = cs.ordered_valid_scens if sort else cs.valid_scens

        def get_table_trace():
            trace = go.Table(
                header=dict(
                    values=["Total", f"{r.C_TOT_:,.0f}", "€ / a"],
                    line=dict(color="lightgray"),
                    align=["left", "right", "left"],
                    font=dict(size=12),
                ),
                cells=dict(
                    values=[
                        ["Operation", "Invest", "Savings", "Depreciation", "Peakload"],
                        [
                            f"{r.C_TOT_op_:,.0f}",
                            f"{r.C_TOT_inv_:,.0f}",
                            f"{cs.REF_scen.res.C_TOT_ - r.C_TOT_:,.0f}",
                            f"{r.C_TOT_inv_ * p.k__AF_:,.0f}",
                            f"{r.P_EG_buyPeak_:,.0f}",
                        ],
                        ["k€/a", "k€", "k€/a", "k€/a", "kW"],
                    ],
                    line=dict(color="lightgray"),
                    align=["left", "right", "left"],
                    font=dict(size=12),
                ),
                domain=dict(x=[0, 0.45], y=[0.4, 1]),
            )
            return trace

        def get_bar_traces():
            d = OrderedDict(
                {
                    sc.id: [sc.res.C_TOT_inv_ * sc.params.k__AF_, sc.res.C_TOT_op_]
                    for sc in css.values()
                }
            )
            df = pd.DataFrame(d, ["Depreciation", "Operation"])

            def get_opacity(id: str) -> float:
                if id == sc.id:
                    return 1.0
                elif id == "REF":
                    return 1.0
                else:
                    return 0.3

            traces = [
                go.Bar(
                    x=df.columns,
                    y=df.loc[ent, :],
                    name=ent,
                    marker=dict(
                        color=["blue", "#de7400"][i], opacity=[get_opacity(id) for id in df.columns]
                    ),
                )
                for i, ent in enumerate(df.index)
            ]

            return traces

        sankey_trace = sc.plot.get_sankey_fig(string_builder_func)["data"][0]
        sankey_trace.update(dict(domain=dict(x=[0.5, 1], y=[0, 1])))

        data = [sankey_trace, get_table_trace()] + get_bar_traces()

        layout = dict(
            title=f"Scenario {sc.id}: {sc.name} ({sc.doc})",
            font=dict(size=12),
            barmode="stack",
            xaxis=dict(domain=[0, 0.45]),
            yaxis=dict(domain=[0, 0.4]),
            legend=dict(x=0, y=0.5),
            margin=dict(t=30, b=5, l=5, r=5),
        )

        if self.optimize_layout_for_reveal_slides:
            layout = hp.optimize_plotly_layout_for_reveal_slides(layout)

        return go.Figure(data=data, layout=layout)

    def table(
        self,
        what: str = "p",
        show_unit: bool = True,
        show_doc: bool = True,
        show_src: bool = False,
        show_etype: bool = False,
        show_comp: bool = False,
        show_desc: bool = False,
        show_dims: bool = False,
        gradient: bool = False,
        filter_func: Optional[Callable] = None,
        precision: int = 0,
        caption: bool = False,
    ) -> pdStyler:
        """Creates a table with all scalars.

        Args:
            what: (p)arameters or (v)ariables.
            show_unit: If units are shown.
            show_doc: If entity docs are shown.
        """
        cs = self.cs

        tmp_list = [
            pd.Series(sc.get_var_par_dic(what)[""], name=name) for name, sc in cs.scens_dic.items()
        ]

        df = pd.concat(tmp_list, axis=1)

        if filter_func is not None:
            df = df.loc[df.index.map(filter_func)]

        if show_unit:
            df["Unit"] = [cs.any_scen.get_unit(ent_name) for ent_name in df.index]
        if show_etype:
            df["Etype"] = [hp.get_etype(ent_name) for ent_name in df.index]
        if show_comp:
            df["Comp"] = [hp.get_component(ent_name) for ent_name in df.index]
        if show_desc:
            df["Desc"] = [hp.get_desc(ent_name) for ent_name in df.index]
        if show_doc:
            df["Doc"] = [cs.any_scen.get_doc(ent_name) for ent_name in df.index]
        if show_src:
            df["Src"] = [cs.any_scen.get_src(ent_name) for ent_name in df.index]
        df.index.name = what

        def highlight_diff1(s):
            other_than_REF = s == df.iloc[:, 0]
            return ["color: lightgray" if v else "" for v in other_than_REF]

        def highlight_diff2(s):
            other_than_REF = s != df.iloc[:, 0]
            return ["font-weight: bold" if v else "" for v in other_than_REF]

        left_aligner = list(df.dtypes[df.dtypes == object].index)

        styled_df = (
            df.style.format(precision=precision, thousands=",")
            .apply(highlight_diff1, subset=df.columns[1:])
            .apply(highlight_diff2, subset=df.columns[1:])
            .set_properties(subset=left_aligner, **{"text-align": "left"})
            .set_table_styles([dict(selector="th", props=[("text-align", "left")])])
        )
        if caption:
            styled_df = styled_df.set_caption(
                "Scalar values where <b>bold</b> numbers indicate deviation from <code>REF</code>-scenario."
            )

        if gradient:
            styled_df = styled_df.background_gradient(cmap="OrRd", axis=1)

        return styled_df

    @hp.copy_doc(ScenPlotter.describe, start="Args:")
    def describe(self, **kwargs) -> None:
        """Prints a description of all Parameters and Results for all scenarios."""
        for sc in self.cs.scens_list:
            sc.plot.describe(**kwargs)

    def describe_interact(self, **kwargs):
        cs = self.cs

        def f(sc_name):
            cs.scens_dic[sc_name].plot.describe(**kwargs)

        interact(f, sc_name=cs.scens_ids)

    def times(self, yscale: str = "linear", stacked: bool = True) -> None:
        """Barplot of the calculation times (Params, Vars, Model, Solve).

        Args:
            yscale: 'log' makes the y-axis logarithmic. Default: 'linear'.
            stacked: If bars are stacked.
        """
        cs = self.cs
        df = pd.DataFrame(
            {
                "Params": pd.Series(cs.get_ent("t__params_")),
                "Vars": pd.Series(cs.get_ent("t__vars_")),
                "Model": pd.Series(cs.get_ent("t__model_")),
                "Solve": pd.Series(cs.get_ent("t__solve_")),
            }
        )

        total_time = df.sum().sum()
        fig, ax = plt.subplots(figsize=(12, 3))
        df.plot.bar(
            stacked=stacked,
            ax=ax,
            title=f"Total time: {total_time:,.0f} s (≈ {total_time/60:,.0f} minutes)",
        )
        ax.set(ylabel="Wall time [s]", yscale=yscale)
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles[::-1], labels[::-1], loc="upper left", frameon=False)
        sns.despine()

    def time_table(
        self, gradient: bool = False, caption: bool = False, precision: int = 0
    ) -> pdStyler:
        cs = self.cs
        df = pd.DataFrame(
            {
                "Params": pd.Series(cs.get_ent("t__params_")),
                "Vars": pd.Series(cs.get_ent("t__vars_")),
                "Model": pd.Series(cs.get_ent("t__model_")),
                "Solve": pd.Series(cs.get_ent("t__solve_")),
            }
        )
        styled_df = df.style.format(precision=precision).set_table_styles(
            get_leftAlignedIndex_style()
        )
        if caption:
            styled_df = styled_df.set_caption("Time in seconds")
        if gradient:
            styled_df = styled_df.background_gradient(cmap="OrRd", axis=None)
        return styled_df

    def invest_table(self, gradient: bool = False) -> pdStyler:
        cs = self.cs
        l = dict(
            C_TOT_inv_="Investment costs [k€]",
            C_TOT_invAnn_="Annualized investment costs [k€/a]",
        )
        df = pd.DataFrame(
            {
                desc: pd.DataFrame(
                    {n: sc.balance_values[which] for n, sc in cs.scens_dic.items()}
                ).stack()
                for which, desc in l.items()
            }
        ).unstack(0)

        styled_df = df.style.format("{:,.0f}").set_table_styles(
            get_leftAlignedIndex_style() + get_multiColumnHeader_style(df)
        )
        if gradient:
            styled_df = styled_df.background_gradient(cmap="OrRd")
        return styled_df

    def invest(self, annualized: bool = True) -> go.Figure:
        cs = self.cs
        if annualized:
            ent_name = "C_TOT_invAnn_"
            title = "Annualized Investment cost [k€]"
        else:
            ent_name = "C_TOT_inv_"
            title = "Investment cost [k€]"

        df = pd.DataFrame({n: sc.balance_values[ent_name] for n, sc in cs.scens_dic.items()}).T

        fig = _get_capa_heatmap(df)
        fig.update_layout(
            margin=dict(t=80, l=5, r=5, b=5),
            xaxis=dict(title=dict(text="Component", standoff=0)),
            title=dict(text=title),
        )
        return fig

    def capas(self, include_capx: bool = True) -> go.Figure:
        """Annotated heatmap of existing and new capacities and a barchart of according C_inv
         and C_op.

        Args:
            include_capx: If existing capacities are included.

        """
        cs = self.cs

        df = self._get_capa_for_all_scens(which="CAPn")
        df = df.rename(columns=lambda x: f"<b>{x}</b>")

        if include_capx:
            df2 = self._get_capa_for_all_scens(which="CAPx")
            df = pd.concat([df2, df], sort=False, axis=1)

        fig = _get_capa_heatmap(df)

        ser = pd.Series(cs.get_ent("C_TOT_inv_"))
        fig.add_trace(
            go.Bar(y=ser.index.tolist(), x=ser.values, xaxis="x2", yaxis="y2", orientation="h")
        )

        ser = pd.Series(cs.get_ent("C_TOT_op_"))
        fig.add_trace(
            go.Bar(y=ser.index.tolist(), x=ser.values, xaxis="x3", yaxis="y3", orientation="h")
        )

        unit = cs.REF_scen.get_unit("C_TOT_inv_")
        capx_adder = " (decision variables in <b>bold</b>)" if include_capx else ""
        fig.update_layout(
            margin=dict(t=5, l=5, r=5, b=5),
            xaxis=dict(domain=[0, 0.78], title=f"Capacity [kW or kWh] of component{capx_adder}"),
            xaxis2=dict(domain=[0.80, 0.90], anchor="y2", title=f"C_inv [{unit}]", side="top"),
            yaxis2=dict(anchor="x2", showticklabels=False),
            xaxis3=dict(domain=[0.92, 1], anchor="y3", title=f"C_op [{unit}]", side="top"),
            yaxis3=dict(anchor="x3", showticklabels=False),
            showlegend=False,
        )
        fig.update_yaxes(matches="y")
        return fig

    def capa_table(self, gradient: bool = False, caption: bool = False) -> pdStyler:
        df = pd.DataFrame(
            {which: self._get_capa_for_all_scens(which).stack() for which in ["CAPx", "CAPn"]}
        ).unstack()

        styled_df = df.style.format(precision=0, thousands=",").set_table_styles(
            get_leftAlignedIndex_style() + get_multiColumnHeader_style(df)
        )
        if gradient:
            styled_df = styled_df.background_gradient(cmap="OrRd")
        if caption:
            styled_df = styled_df.set_caption("Existing (CAPx) and new (CAPn) capacity ")
        return styled_df

    def _get_capa_for_all_scens(self, which: str) -> pd.DataFrame:
        """'which' can be 'CAPn' or 'CAPx'"""
        cs = self.cs
        return pd.DataFrame(
            {n: sc.get_CAP(which=which, agg=True) for n, sc in cs.scens_dic.items()}
        ).T

    def _get_correlation(self, ent1: str, ent2: str) -> pd.Series:
        """EXPERIMENTAL: Returns correlation coefficients between two entities for all scenarios."""
        d = dict()
        cs = self.cs
        for sc in cs.scens_list:
            ser1 = sc.get_entity(ent1)
            ser2 = sc.get_entity(ent2)
            d[sc.id] = ser1.sum(level=0).corr(ser2.sum(level=0))
        return pd.Series(d)


def _get_capa_heatmap(df) -> go.Figure:
    data = df.where(df > 0)
    fig = ff.create_annotated_heatmap(
        data.values,
        x=data.columns.tolist(),
        y=data.index.tolist(),
        annotation_text=data.applymap(float_to_int_to_string).values,
        showscale=False,
        colorscale="OrRd",
        font_colors=["white", "black"],
    )
    fig.update_layout(
        xaxis=dict(showgrid=False, side="top"),
        yaxis=dict(showgrid=False, autorange="reversed", title="Scenario"),
        width=200 + len(df.columns) * 40,
        height=200 + len(df) * 5,
    )
    set_font_size(fig=fig, size=9)
    make_high_values_white(fig=fig, data=data)
    return fig


def make_high_values_white(fig, data, diverging: bool = False) -> None:
    if diverging:
        data = data.abs()
    minz = data.min().min()
    maxz = data.max().max()
    threshold = (minz + maxz) / 2
    for i in range(len(fig.layout.annotations)):
        ann_text = fig.layout.annotations[i].text
        if ann_text != NAN_REPRESENTATION:
            f = float(ann_text.replace(",", ""))
            if diverging:
                f = abs(f)
            if f > threshold:
                fig.layout.annotations[i].font.color = "white"


def set_font_size(fig, size: int = 9) -> None:
    for i in range(len(fig.layout.annotations)):
        fig.layout.annotations[i].font.size = size


def grey(s: str):
    return f"<span style='font-size:small;color:grey;font-family:monospace;'>{s}</span>"


def float_to_int_to_string(afloat):
    return f"{afloat:,.0f}".replace("nan", NAN_REPRESENTATION)


def float_to_string_with_precision_1(afloat):
    return f"{afloat:.1f}".replace("nan", NAN_REPRESENTATION)


def float_to_string_with_precision_2(afloat):
    return f"{afloat:.2f}".replace("nan", NAN_REPRESENTATION)


def get_divider_nums(df):
    ser = pd.Series(df.columns.codes[0]).diff()
    return ser[ser != 0].index.tolist()[1:]


def get_divider(column_loc):
    return {
        "selector": f".col{column_loc}",
        "props": [
            ("border-left", "1px solid black"),
        ],
    }


def get_multiColumnHeader_style(df):
    cols = {
        "selector": "th.col_heading",
        "props": [("text-align", "center")],
    }
    return [cols] + [get_divider(i) for i in get_divider_nums(df)]


def get_leftAlignedIndex_style():
    return [
        dict(
            selector="th.row_heading",
            props=[
                ("text-align", "left"),
            ],
        )
    ]


def get_pareto_title(pareto: pd.DataFrame, units) -> str:
    ce_saving = pareto.iloc[0, 1] - pareto.iloc[:, 1].min()
    ce_saving_rel = 100 * (pareto.iloc[0, 1] - pareto.iloc[:, 1].min()) / pareto.iloc[0, 1]
    c_saving = pareto.iloc[0, 0] - pareto.iloc[:, 0].min()
    c_saving_rel = 100 * (pareto.iloc[0, 0] - pareto.iloc[:, 0].min()) / pareto.iloc[0, 0]
    return (
        f"Max. cost savings: {c_saving:,.2f} {units['C_TOT_']} ({c_saving_rel:.2f}%)\n"
        f"Max. carbon savings: {ce_saving:.2f} {units['CE_TOT_']} ({ce_saving_rel:.2f}%)"
    )
