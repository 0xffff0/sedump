# Copyright 2014-2015, Tresys Technology, LLC
#
# This file is part of SETools.
#
# SETools is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 2.1 of
# the License, or (at your option) any later version.
#
# SETools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with SETools.  If not, see
# <http://www.gnu.org/licenses/>.
#
import itertools
import logging

import networkx as nx
from networkx.exception import NetworkXError, NetworkXNoPath


__all__ = ['InfoFlowAnalysis']


class InfoFlowAnalysis(object):

    """Information flow analysis."""

    def __init__(self, policy, perm_map, minweight=1, exclude=None):
        """
        Parameters:
        policy      The policy to analyze.
        perm_map    The permission map or path to the permission map file.
        minweight   The minimum permission weight to include in the analysis.
                    (default is 1)
        exclude     The types excluded from the information flow analysis.
                    (default is none)
        """
        self.log = logging.getLogger(self.__class__.__name__)

        self.policy = policy

        self.set_min_weight(minweight)
        self.set_perm_map(perm_map)
        self.set_exclude(exclude)
        self.rebuildgraph = True
        self.rebuildsubgraph = True

        self.G = nx.DiGraph()
        self.subG = None

    def set_min_weight(self, weight):
        """
        Set the minimum permission weight for the information flow analysis.

        Parameter:
        weight      Minimum permission weight (1-10)

        Exceptions:
        ValueError  The minimum weight is not 1-10.
        """
        if not 1 <= weight <= 10:
            raise ValueError(
                "Min information flow weight must be an integer 1-10.")

        self.minweight = weight
        self.rebuildsubgraph = True

    def set_perm_map(self, perm_map):
        """
        Set the permission map used for the information flow analysis.

        Parameter:
        perm_map    The permission map.

        Exceptions:
        TypeError   The map is not a file path or permission map object.
        """
        self.perm_map = perm_map

        self.rebuildgraph = True
        self.rebuildsubgraph = True

    def set_exclude(self, exclude):
        """
        Set the types to exclude from the information flow analysis.

        Parameter:
        exclude         A list of types.
        """

        if exclude:
            self.exclude = [self.policy.lookup_type(t) for t in exclude]
        else:
            self.exclude = []

        self.rebuildsubgraph = True

    def shortest_path(self, source, target):
        """
        Generator which yields one shortest path between the source
        and target types (there may be more).

        Parameters:
        source   The source type.
        target   The target type.

        Yield: generator(paths)

        steps    Generator which yields steps in the path.
        """
        s = self.policy.lookup_type(source)
        t = self.policy.lookup_type(target)

        if self.rebuildsubgraph:
            self._build_subgraph()

        self.log.info("Generating one shortest path from {0} to {1}...".format(s, t))

        try:
            yield self.__generate_steps(nx.shortest_path(self.subG, s, t))
        except (NetworkXNoPath, NetworkXError):
            # NetworkXError: the type is valid but not in graph, e.g.
            # excluded or disconnected due to min weight
            # NetworkXNoPath: no paths or the target type is
            # not in the graph
            pass

    def all_paths(self, source, target, maxlen=2):
        """
        Generator which yields all paths between the source and target
        up to the specified maximum path length.  This algorithm
        tends to get very expensive above 3-5 steps, depending
        on the policy complexity.

        Parameters:
        source    The source type.
        target    The target type.
        maxlen    Maximum length of paths.

        Yield: generator(paths)

        steps    Generator which yields steps in the path.
        """
        if maxlen < 1:
            raise ValueError("Maximum path length must be positive.")

        s = self.policy.lookup_type(source)
        t = self.policy.lookup_type(target)

        if self.rebuildsubgraph:
            self._build_subgraph()

        self.log.info("Generating all paths from {0} to {1}, max len {2}...".format(s, t, maxlen))

        try:
            for path in nx.all_simple_paths(self.subG, s, t, maxlen):
                yield self.__generate_steps(path)
        except (NetworkXNoPath, NetworkXError):
            # NetworkXError: the type is valid but not in graph, e.g.
            # excluded or disconnected due to min weight
            # NetworkXNoPath: no paths or the target type is
            # not in the graph
            pass

    def all_shortest_paths(self, source, target):
        """
        Generator which yields all shortest paths between the source
        and target types.

        Parameters:
        source   The source type.
        target   The target type.

        Yield: generator(paths)

        steps    Generator which yields steps in the path.
        """
        s = self.policy.lookup_type(source)
        t = self.policy.lookup_type(target)

        if self.rebuildsubgraph:
            self._build_subgraph()

        self.log.info("Generating all shortest paths from {0} to {1}...".format(s, t))

        try:
            for path in nx.all_shortest_paths(self.subG, s, t):
                yield self.__generate_steps(path)
        except (NetworkXNoPath, NetworkXError, KeyError):
            # NetworkXError: the type is valid but not in graph, e.g.
            # excluded or disconnected due to min weight
            # NetworkXNoPath: no paths or the target type is
            # not in the graph
            # KeyError: work around NetworkX bug
            # when the source node is not in the graph
            pass

    def infoflows(self, type_, out=True):
        """
        Generator which yields all information flows in/out of a
        specified source type.

        Parameters:
        source  The starting type.

        Keyword Parameters:
        out     If true, information flows out of the type will
                be returned.  If false, information flows in to the
                type will be returned.  Default is true.

        Yield: generator(steps)
        """
        s = self.policy.lookup_type(type_)

        if self.rebuildsubgraph:
            self._build_subgraph()

        self.log.info("Generating all infoflows out of {0}...".format(s))

        if out:
            flows = self.subG.out_edges_iter(s)
        else:
            flows = self.subG.in_edges_iter(s)

        try:
            for source, target in flows:
                yield Edge(self.subG, source, target)
        except NetworkXError:
            # NetworkXError: the type is valid but not in graph, e.g.
            # excluded or disconnected due to min weight
            pass

    def get_stats(self):  # pragma: no cover
        """
        Get the information flow graph statistics.

        Return: tuple(nodes, edges)

        nodes    The number of nodes (types) in the graph.
        edges    The number of edges (information flows between types)
                 in the graph.
        """
        return (self.G.number_of_nodes(), self.G.number_of_edges())

    #
    # Internal functions follow
    #

    def __generate_steps(self, path):
        """
        Generator which yields each information flow step in a path.

        Parameter:
        path   A list of graph node names representing an information flow path.

        Yield: step (A graph edge)
        """
        for s in range(1, len(path)):
            yield Edge(self.subG, path[s - 1], path[s])

    #
    #
    # Graph building functions
    #
    #
    # 1. _build_graph determines the flow in each direction for each TE
    #    rule and then expands the rule.  All information flows are
    #    included in this main graph: memory is traded off for efficiency
    #    as the main graph should only need to be rebuilt if permission
    #    weights change.
    # 2. __add_edge does the actual graph insertions.  Nodes are implictly
    #    created by the edge additions, i.e. types that have no info flow
    #    do not appear in the graph.
    # 3. _build_subgraph derives a subgraph which removes all excluded
    #    types (nodes) and edges (information flows) which are below the
    #    minimum weight. This subgraph is rebuilt only if the main graph
    #    is rebuilt or the minimum weight or excluded types change.

    def _build_graph(self):
        self.G.clear()

        self.perm_map.map_policy(self.policy)

        self.log.info("Building graph from {0}...".format(self.policy))

        for rule in self.policy.terules():
            if rule.ruletype != "allow":
                continue

            (rweight, wweight) = self.perm_map.rule_weight(rule)

            for s, t in itertools.product(rule.source.expand(), rule.target.expand()):
                # only add flows if they actually flow
                # in or out of the source type type
                if s != t:
                    if wweight:
                        edge = Edge(self.G, s, t, create=True)
                        edge.rules.append(rule)
                        edge.weight = wweight

                    if rweight:
                        edge = Edge(self.G, t, s, create=True)
                        edge.rules.append(rule)
                        edge.weight = rweight

        self.rebuildgraph = False
        self.rebuildsubgraph = True
        self.log.info("Completed building graph.")

    def _build_subgraph(self):
        if self.rebuildgraph:
            self._build_graph()

        self.log.info("Building subgraph...")
        self.log.debug("Excluding {0!r}".format(self.exclude))
        self.log.debug("Min weight {0}".format(self.minweight))

        # delete excluded types from subgraph
        nodes = [n for n in self.G.nodes() if n not in self.exclude]
        self.subG = self.G.subgraph(nodes)

        # delete edges below minimum weight.
        # no need if weight is 1, since that
        # does not exclude any edges.
        if self.minweight > 1:
            delete_list = []
            for s, t in self.subG.edges_iter():
                edge = Edge(self.subG, s, t)
                if edge.weight < self.minweight:
                    delete_list.append(edge)

            self.subG.remove_edges_from(delete_list)

        self.rebuildsubgraph = False
        self.log.info("Completed building subgraph.")


class EdgeAttrList(object):

    """
    A descriptor for edge attributes that are lists.

    Parameter:
    name    The edge property name
    """

    def __init__(self, propname):
        self.name = propname

    def __get__(self, obj, type=None):
        return obj.G[obj.source][obj.target][self.name]

    def __set__(self, obj, value):
        # None is a special value to initialize
        if value is None:
            obj.G[obj.source][obj.target][self.name] = []
        else:
            raise ValueError("{0} lists should not be assigned directly".format(self.name))

    def __delete__(self, obj):
        # in Python3 a .clear() function was added for lists
        # keep this implementation for Python 2 compat
        del obj.G[obj.source][obj.target][self.name][:]


class EdgeAttrIntMax(object):

    """
    A descriptor for edge attributes that are non-negative integers that always
    keep the max assigned value until re-initialized.

    Parameter:
    name    The edge property name
    """

    def __init__(self, propname):
        self.name = propname

    def __get__(self, obj, type=None):
        return obj.G[obj.source][obj.target][self.name]

    def __set__(self, obj, value):
        # None is a special value to initialize
        if value is None:
            obj.G[obj.source][obj.target][self.name] = 0
        else:
            current_value = obj.G[obj.source][obj.target][self.name]
            obj.G[obj.source][obj.target][self.name] = max(current_value, value)


class Edge(object):

    """
    A graph edge.  Also used for returning information flow steps.

    Parameters:
    source      The source type of the edge.
    target      The target type of the edge.

    Keyword Parameters:
    create      (T/F) create the edge if it does not exist.
                The default is False.
    """

    rules = EdgeAttrList('rules')

    # use capacity to store the info flow weight so
    # we can use network flow algorithms naturally.
    # The weight for each edge is 1 since each info
    # flow step is no more costly than another
    # (see below add_edge() call)
    weight = EdgeAttrIntMax('capacity')

    def __init__(self, graph, source, target, create=False):
        self.G = graph
        self.source = source
        self.target = target

        # a bit of a hack to make edges work
        # in NetworkX functions that work on
        # 2-tuples of (source, target)
        # (see __getitem__ below)
        self.st_tuple = (source, target)

        if not self.G.has_edge(source, target):
            if create:
                self.G.add_edge(source, target, weight=1)
                self.rules = None
                self.weight = None
            else:
                raise ValueError("Edge does not exist in graph")

    def __getitem__(self, key):
        return self.st_tuple[key]
