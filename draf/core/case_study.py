from __future__ import annotations

import datetime
import logging
import pickle
import textwrap
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd
from tqdm.auto import tqdm

from draf import helper as hp
from draf import paths
from draf.core.datetime_handler import DateTimeHandler
from draf.core.draf_base_class import DrafBaseClass
from draf.core.entity_stores import Dimensions, Params, Scenarios
from draf.core.scenario import Scenario
from draf.core.time_series_prepper import TimeSeriesPrepper
from draf.plotting.cs_plotting import CsPlotter
from draf.plotting.scen_plotting import ScenPlotter

# TODO: put all logging functionality into a logger.py file.
fmt = "%(levelname)s:%(name)s:%(funcName)s():%(lineno)i:\n    %(message)s"
logging.basicConfig(level=logging.WARN, format=fmt)
logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARN)


def _load_pickle_object(fp) -> Any:
    with open(fp, "rb") as f:
        obj = pickle.load(f)
    return obj


def open_casestudy(fp) -> CaseStudy:
    cs = CaseStudy()
    cs.__dict__ = _load_pickle_object(fp).__dict__
    cs.plot = CsPlotter(cs=cs)
    for sc in cs.scens.get_all().values():
        sc.plot = ScenPlotter(sc=sc)
        sc.prep = TimeSeriesPrepper(sc=sc)

    logger.info(f"opened CaseStudy from {fp}")

    return cs


def open_latest_casestudy(name: str, verbose: bool = True) -> CaseStudy:
    fd = paths.RESULTS / name
    files = sorted(list(fd.glob("*.p")))
    fp = files[-1]
    if verbose:
        print(f"Open CaseStudy from {fp.name}")
    return open_casestudy(fp)


class CaseStudy(DrafBaseClass, DateTimeHandler):
    """Contains all relevant information for a case study: timeranges, optimization models,
    scenarios and functions.

    Args:
        name: Name string of case study.
        year: Year
        freq: Default time step. E.g. '60min'.
        country: Country code.
        doc: Documentation string of case study.

    """

    def __init__(
        self,
        name: str = "test",
        year: int = 2019,
        freq: str = "60min",
        country: str = "DE",
        doc: str = "No doc available.",
        coords: Tuple[float, float] = None,
        obj_vars: Tuple[str, str] = ("C_TOT_", "CE_TOT_"),
    ):
        assert freq in ["15min", "30min", "60min"]

        self.name = name
        self.doc = doc
        self._set_dtindex(year=year, freq=freq)
        self.country = country
        self.coords = coords
        self.scens = Scenarios()
        self.plot = CsPlotter(cs=self)
        self.dims = Dimensions()
        self.params = Params()
        self.obj_vars = obj_vars

    def __repr__(self):
        preface = "<{} object>".format(self.__class__.__name__)
        l = []
        excluded = ["scens", "dtindex", "dtindex_custom", "scen_df"]
        for k, v in self.get_all().items():
            if k in excluded:
                v = "[...]"
            l.append(f"• {k}: {v}")
        s_dt_info = textwrap.indent(self.dt_info, "  ⤷ ")
        l.append(f"• dt_info:\n{s_dt_info}")
        main = "\n".join(l)
        return f"{preface}\n{main}"

    @property
    def scens_ids(self) -> List[str]:
        """Returns a list of all scenario IDs."""
        return list(self.scens_dic.keys())

    @property
    def scens_list(self) -> List[Scenario]:
        """Returns a list of all scenario objects."""
        return list(self.scens_dic.values())

    @property
    def scens_dic(self) -> Dict[str, Scenario]:
        """Returns a dict of all scenario objects."""
        return self.scens.get_all()

    @property
    def any_scen(self) -> Scenario:
        """Returns any scenario object."""
        return self.scens_list[0]

    @property
    def valid_scens(self):
        """Returns a Dict of scenario objects with results."""
        return {name: sc for name, sc in self.scens_dic.items() if hasattr(sc, "res")}

    @property
    def ordered_valid_scens(self):
        """Returns an OrderedDict of scenario objects sorted by descending system costs."""
        return OrderedDict(
            sorted(self.valid_scens.items(), key=lambda kv: kv[1].res.C_TOT_, reverse=True)
        )

    @property
    def _res_fp(self) -> Path:
        """Returns the path to the case study's default result directory."""
        fp = paths.RESULTS / self.name
        fp.mkdir(exist_ok=True)
        return fp

    @property
    def pareto(self) -> pd.DataFrame:
        """Returns a table of all pareto points."""
        df = pd.DataFrame(columns=self.obj_vars)

        for name, sc in self.scens_dic.items():
            df.loc[name] = [getattr(sc.res, var) for var in self.obj_vars]
        return df

    @property
    def REF_scen(self) -> Scenario:
        """Returns the reference scenario i.e. the scenario with the id=REF or if that not exists
        the first scenario."""
        try:
            return getattr(self.scens, "REF")
        except AttributeError:
            return self.scens_list[0]

    def set_solver_params(self, **kwargs) -> CaseStudy:
        """Set some gurobi solver parameters e.g.:
        LogFile,
        LogToConsole,
        OutputFlag,
        MIPGap,
        MIPFocus: solver focuses on:
            1: feasible solutions quickly,
            2: optimality,
            3: bound.
        """
        for sc in self.scens_list:
            for k, v in kwargs.items():
                sc.mdl.setParam(k, v, verbose=False)

        return self

    def activate_vars(self) -> None:
        for sc in self.scens_list:
            sc._activate_vars()

    def add_REF_scen(self, name="REF", doc="Reference scenario", **scenario_kwargs) -> Scenario:
        """Adds a reference scenario and returns it."""
        sc = self.add_scen(id="REF", name=name, doc=doc, based_on=None, **scenario_kwargs)
        return sc

    def add_scen(
        self,
        id: Optional[str] = None,
        name: str = "",
        doc: str = "",
        based_on: Optional[str] = "REF",
        based_on_last: bool = False,
    ) -> Scenario:
        """Add a Scenario with a name, a describing doc-string and a link to a model.

        Args:
            id: Scenario id string which must be unique and without special characters. If is None,
                the scenarios are numbered consecutively.
            name: Scenario name string.
            doc: Scenario doc string. This can be a longer string
            based_on: Id of scenario which is copied. `based_on` can be set to None to create a new
                scenario from scratch.
            based_on_last: If the most recent scenario is taken as basis.
        """
        if based_on_last:
            based_on = self.scens_ids[-1]
            doc = f"{based_on} + {doc}"

        if id is None:
            id = f"sc{len(self.scens_list)}"

        if based_on is None:
            sc = Scenario(
                id=id,
                name=name,
                doc=doc,
                coords=self.coords,
                year=self.year,
                country=self.country,
                freq=self.freq,
                cs_name=self.name,
                dtindex=self.dtindex,
                dtindex_custom=self.dtindex_custom,
                t1=self._t1,
                t2=self._t2,
            )
        else:
            sc = getattr(self.scens, based_on)._special_copy()
            sc.id = id
            sc.name = name
            sc.doc = doc

        setattr(self.scens, id, sc)
        return sc

    def add_scens(
        self,
        scen_vars: Optional[List[Tuple[str, str, List]]] = None,
        nParetoPoints: int = 0,
        del_REF: bool = False,
        based_on: str = "REF",
    ) -> CaseStudy:
        """Add scenarios from a list of tuples containing a long and short entity name and its
        desired variations. For every possible permutation a scenario is created. If the entity
        is a parameter the old parameter will be overwritten. If the entity is a variable the lower
        and upper bounds will be fixed to the desired value.

        Args:
            scen_vars: List of tuples containing a long and short entity name and its
                desired variations. The syntax can be taken from this example:
                ```
                scen_vars = [
                    ("c_GRID_T", "t", ["c_GRID_RTP_T", "c_GRID_TOU_T"]]),
                    ("P_PV_CAPx_", "p", [0, 10, 20])
                ]
                ```
                In the first tuple the parameter 'c_GRID_T' is set to the parameter 'c_GRID_RTP_T'
                and then to the parameter 'c_GRID_TOU_T'. In the second tuple, the parameter
                'P_PV_CAPx_' is set to the different values of the list [0, 10, 20]. Since every
                possible combination is created as a scenario, in this example 6 scenarios are
                created.
            nParetoPoints: Number of desired Pareto-point for each energy system configuration.
            del_REF: If the reference scenario is deleted after the creation of the scenarios.
            based_on: ID string of the scenario used as base-scenario for all created scenarios.

        Note:
            The attributes `scen_vars` and `scen_df` are set to the CaseStudy.

        """
        if scen_vars is None:
            if nParetoPoints > 0:
                scen_vars = []
            else:
                RuntimeError("If `nParetoPoints` = 0, scens_vars must not be None.")

        if nParetoPoints > 0:
            scen_vars.append(("k_PTO_alpha_", "a", np.linspace(0, 1, nParetoPoints)))

        self.scen_vars = scen_vars

        names_long, names_short, value_lists = zip(*scen_vars)
        df = pd.DataFrame(index=pd.MultiIndex.from_product(value_lists, names=names_long))
        df = df.reset_index()
        dfn = df.T.astype(str).apply(lambda x: names_short + x)
        df.index = ["_".join(dfn[x].values) for x in dfn]
        self.scen_df = scen_df = df.T

        for sc_name, ser in scen_df.items():
            doc_list = [f"{x[0]}={x[1]}" for x in zip(ser.index, ser.values)]
            long_doc = "; ".join(doc_list)
            sc = self.add_scen(
                id=f"sc{len(self.scens_dic)}", name=sc_name, doc=long_doc, based_on=based_on
            )
            sc.update_params(timelog_params_=0)

            for ent_name, value in ser.items():
                if isinstance(value, str):
                    value = sc.get_entity(value)

                if ent_name in sc.vars._meta:
                    sc.vars._meta[ent_name]["lb"] = value
                    sc.vars._meta[ent_name]["ub"] = value
                    logger.info(f"Updated variable {ent_name} on scenario {sc.id}.")

                else:
                    sc.update_params(**{ent_name: value})
                    logger.info(f"Updated parameter {ent_name} on scenario {sc.id}.")

        if del_REF:
            delattr(self.scens, based_on)

        return self

    def _load_cs_from_file(self, fp: str) -> Dict:
        with open(fp, "rb") as f:
            cs = pickle.load(f)
        return cs

    def save(self, name: str = "", fp: Any = None):
        """Saves the CaseStudy object to a pickle-file. The current timestamp is used for a
        unique file-name.

        Args:
            name: This string is appended to the time stamp.
            fp: Filepath which overwrites the default, which uses a time stamp.

        Note:
            iPython autoreload function must be turned off.
        """
        date_time = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

        if fp is None:
            fp = self._res_fp / f"{date_time}_{name}.p"
        else:
            fp = Path(fp)

        try:
            with open(fp, "wb") as f:
                pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info(f"saved CaseStudy to {fp}")
        except pickle.PicklingError as e:
            logger.error(f"{e}: Solution: Please deactivate Ipython's autoreload to pickle.")
            return None

        size = hp.sizeof_fmt(fp.stat().st_size)
        print(f"CaseStudy saved to {fp.as_posix()} ({size})")

    def set_time_horizon(
        self,
        start: Union[int, str],
        steps: Optional[int] = None,
        end: Optional[Union[int, str]] = None,
    ) -> CaseStudy:
        """Reduces the time horizon for the analysis from the whole year.

        Examples:
            >>> cs.set_time_horizon(start="May1 00:00", end="Jun1 23:00")

            >>> cs.set_time_horizon(start="May1 00:00", steps=24*30)
        """
        t1, t2 = self._get_integer_locations(start, steps, end)
        self.dtindex_custom = self.dtindex[t1 : t2 + 1]
        assert self.dtindex_custom[0] == self.dtindex[t1]
        assert self.dtindex_custom[-1] == self.dtindex[t2]
        self._t1 = t1
        self._t2 = t2
        return self

    def get_ent_info(self, ent_name: str, show_doc: bool = True, **kwargs) -> str:
        """Returns a string with available information about an entity."""
        s = ""
        if show_doc:
            s += f"{ent_name}: {self.any_scen.get_doc(ent_name)}\n\n"

        for sc in self.scens_list:
            s += f"{sc.id}: {sc.get_ent_info(ent_name, **kwargs)}"

        return s

    def improve_pareto_and_set_model(self, model_func) -> CaseStudy:
        """Convenience function."""
        self.improve_pareto_norm_factors(model_func=model_func)
        self.set_model(model_func=model_func)
        return self

    def improve_pareto_norm_factors(
        self, model_func: Callable, adjust_factor: float = 1.0, basis_scen_id: str = "REF"
    ) -> CaseStudy:
        """Solves the given model for both extreme points (alpha=0 and alpha=1) in order to
        determine good pareto norm factors k_PTO_C_ and k_PTO_CE_, which are then set for all scenarios.
        """

        nC = []
        nCE = []

        for i in [0, 1]:
            sc = self.add_scen(str(i), name="pareto_improver", based_on=basis_scen_id)
            sc.params.k_PTO_alpha_ = i
            sc.set_model(model_func)
            sc.optimize(show_results=False, outputFlag=False)
            nC.append(sc.res.C_TOT_ * adjust_factor)
            nCE.append(sc.res.CE_TOT_)
            delattr(self.scens, str(i))

        for sc in self.scens_list:
            sc.params.k_PTO_C_ = 1e3 / np.array(nC).mean()
            sc.params.k_PTO_CE_ = 1e3 / np.array(nCE).mean()
            logger.info(
                f"C/CE Pareto norm factors set to {sc.params.k_PTO_C_} and {sc.params.k_PTO_CE_}"
            )
        return self

    def set_params(self, params_func: Callable, scens: List = None) -> CaseStudy:
        """Executes the `params_func` for for multiple scenarios at once."""
        if scens is None:
            scens = self.scens_list

        for sc in scens:
            sc.set_params(params_func)

        return self

    def set_model(
        self,
        model_func: Callable,
        speed_up: bool = True,
        scens: Optional[List] = None,
        mdl_language: str = "gp",
    ) -> CaseStudy:
        """Set model for multiple scenarios at once."""
        if scens is None:
            scens = self.scens_list

        pbar = tqdm(scens)
        for sc in pbar:
            pbar.set_description(f"Build model for {sc.id}")
            sc.set_model(model_func, speed_up=speed_up, mdl_language=mdl_language)

        return self

    @hp.copy_doc(Scenario.optimize)
    def optimize(
        self,
        scens: Optional[Iterable] = None,
        postprocess_func: Optional[Callable] = None,
        **optimize_kwargs,
    ) -> CaseStudy:
        """Optimize multiple scenarios at once."""
        if scens is None:
            scens = self.scens_list

        # Since lists are dynamic, the current status has to be frozen in a inmutable tuple to
        # avoid the interactive status bar description being modified later as further scenarios
        # are added.
        scens = tuple(scens)

        pbar = tqdm(scens)
        for sc in pbar:
            pbar.set_description(f"Solve {sc.id}")
            sc.optimize(postprocess_func=postprocess_func, **optimize_kwargs)

        if all([sc._is_optimal for sc in scens]):
            mean = np.array([sc.params.timelog_solve_ for sc in scens]).mean()
            print(
                f"Successfully solved {len(scens)} scenarios with an average solving time "
                f"of {mean:.3} seconds."
            )

        return self

    def get_ent(self, ent_name: str) -> Dict:
        """Returns the data of an entity for all scenarios."""
        return {name: sc.get_entity(ent_name) for name, sc in self.scens_dic.items()}

    def import_scens(
        self, other_cs: CaseStudy, exclude: List[str] = None, include: List[str] = None
    ):
        """Imports scenarios including all results from another CaseStudy object.

        Args:
            other_cs: Source casestudy object.
            exclude: List of scenario ID's which are explicitly not considered.
            include: List of scenario ID's which are explicitly considered.
        """
        scen_dic = other_cs.scens.get_all()
        scens_to_import = scen_dic.keys()

        if exclude is not None:
            scens_to_import = [n for n in scens_to_import if n not in exclude]

        if include is not None:
            scens_to_import = [n for n in scens_to_import if n in include]

        for name, sc in scen_dic.items():
            if name in scens_to_import:
                setattr(self.scens, name, sc)
