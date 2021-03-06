"""Winged-Edge Data Structure and Functions


TO DO

- handle hole region explicitly
- relax assumption about integer node ids
- test on other edge cases besides Eberly

"""


__author__ = "Sergio Rey <sjsrey@gmail.com>, Jay Laura <jlaura@asu.edu>"

import ast
import json
import cPickle
import numpy as np
import pysal as ps
from pysal.cg import Point, Polygon, LineSegment, KDTree
from pysal.cg.standalone import get_points_dist
import copy
import operator
import math
from itertools import combinations
import collections


class WED(object):
    """Winged-Edge Data Structure


    """

    def __init__(self, edges=None, coords=None):

        self.start_c = None
        self.start_cc = None
        self.end_c = None
        self.end_cc = None
        self.region_edge = None
        self.node_edge = None
        self.right_polygon = None
        self.left_polygon = None
        self.start_node = None
        self.end_node = None
        self.node_coords = None
        self.edge_list = []

        if edges is not None and coords is not None:
            #Check for single edges and double if needed
            edges = self.check_edges(edges)
            self.edge_list[:] = edges

            #Create the WED object
            self.extract_wed(edges, coords)

    def check_edges(self, edges):
        """
        Validator to ensure that edges are double.

        Parameters
        ----------
        edges: list
            edges connecting nodes in the network

        Returns
        -------
        dbl_edges / edges: list
            Either the original edges or double edges
        """

        seen = set()
        seen_add = seen.add
        seen_twice = set()
        for e in edges:
            if e in seen:
                seen_twice.add(e)
            seen_add(e)
            seen_add((e[1], e[0]))
        if len(list(seen_twice)) != len(edges) / 2:
            dbl_edges = []
            for e in edges:
                dbl_edges.append(e)
                dbl_edges.append((e[1], e[0]))
            return dbl_edges
        else:
            return edges

    def enum_links_node(self, node):
        """
        Enumerate links in cw order around a node

        Parameters
        ----------

        node: string/int
            id for the node in wed


        Returns
        -------

        links: list
            links ordered cw around node
        """

        links = []
        if node not in self.node_edge:
            return links
        l0 = self.node_edge[node]
        links.append(l0)
        l = l0
        v = node
        searching = True
        while searching:
            if v == l[0]:
                l = self.start_c[l]
            else:
                l = self.end_c[l]
            if (l is None) or (set(l) == set(l0)):
                searching = False
            else:
                links.append(l)
        return links

    def enum_edges_region(self, region):
        """
        Enumerate the edges of a region/polygon in cw order

        Parameters
        ----------

        region: id for the region in wed


        Returns
        -------

        links: list of links ordered cw that define the region/polygon

        """
        right_polygon = self.right_polygon
        end_cc = self.end_cc
        start_cc = self.start_cc
        region_edge = self.region_edge
        l0 = region_edge[region]
        l = copy.copy(l0)
        edges = []
        edges.append(l)
        traveling = True
        while traveling:
            if region == right_polygon[l]:
                l = end_cc[l]
            else:
                l = start_cc[l]
            edges.append(l)
            if set(l) == set(l0):
                traveling = False
        return edges

    def w_links(self):
        """
        Generate Weights object for links in a WED

        Parameters
        ----------
        None

        Returns

        ps.W(neighbors): PySAL Weights Dict
        """
        nodes = self.node_edge.keys()
        neighbors = {}
        for node in nodes:
            lnks = self.enum_links_node(node)
            # put i,j s.t. i < j
            lnks = [tuple(sorted(lnk)) for lnk in lnks]
            for comb in combinations(range(len(lnks)), 2):
                l, r = comb
                if lnks[l] not in neighbors:
                    neighbors[lnks[l]] = []
                neighbors[lnks[l]].append(lnks[r])
                if lnks[r] not in neighbors:
                    neighbors[lnks[r]] = []
                neighbors[lnks[r]].append(lnks[l])
        return ps.W(neighbors)

    def _filament_links_node(self, node, node_edge, start_c, end_c):
        """
        Private method that duplicates enum_links_around_node, but
         is callable before the WED is generated.  This is used
         for filament insertion.
        """
        links = []
        if node not in node_edge:
            return links
        l0 = node_edge[node]
        links.append(l0)
        l = l0
        v = node
        searching = True
        while searching:
            if v == l[0]:
                l = start_c[l]
            else:
                l = end_c[l]
            if (l is None) or (set(l) == set(l0)):
                searching = False
            else:
                links.append(l)
        return links

    def extract_wed(self, edges, coords):
        # helper functions to determine relative position of vectors
        def _dotproduct(v1, v2):
            return sum((a * b) for a, b in zip(v1, v2))

        def _length(v):
            return math.sqrt(_dotproduct(v, v))

        def _angle(v1, v2):
            return math.acos(_dotproduct(v1, v2) / (_length(v1) * _length(v2)))

        """
        Extract the Winged Edge Data structure for a planar graph


        Arguments
        ---------

        edges:  list
                tuples of origin, destination nodes for each edge

        coords: dict
                key is node id, value is a tuple of x,y coordinates for the node


        Returns
        -------
        wed: Dictionary holding the WED with 10 keys

            start_node: dict
                        key is node, value is edge with node as start node

            end_node:   dict
                        key is node, value is edge with node as end node

            right_polygon: dict
                            key is edge, value is id of right polygon to edge

            left_polygon: dict
                        key is edge, value is id of left polygon to edge

            node_edge: dict
                        key is node, value is edge associated with the node

            region_edge: dict
                        key is region, value is an edge on perimeter of region

            start_c:   dict
                        key is edge, value is first edge encountered when rotating
                        clockwise around edge start node

            start_cc:  dict
                        key is edge, value is first edge encountered when rotating
                        counterclockwise around edge start node

            end_c:     dict
                        key is edge, value is first edge encountered when rotating
                        clockwise around edge start end node

            end_cc:    dict
                        key is edge, value is first edge encountered when rotating
                        counterclockwise around edge start end node

        """

        # coords will be destroyed so keep a copy around
        coords_org = coords.copy()

        # find minimum cycles, filaments and isolated nodes
        pos = coords.values()
        mcb = self.regions_from_graph(coords, edges)

        regions = mcb['regions']
        edges = mcb['edges']
        vertices = mcb['vertices']
        start_node = {}
        end_node = {}
        for edge in edges:
            if edge[0] != edge[1]:  # no self-loops
                start_node[edge] = edge[0]
                end_node[edge] = edge[1]

        # Right polygon for each edge in each region primitive
        #
        # Also define start_c, end_cc for each polygon edge and
        #  start_cc and end_c for its twin

        right_polygon = {}
        left_polygon = {}
        region_edge = {}
        start_c = {}
        start_cc = {}
        end_c = {}
        end_cc = {}
        node_edge = {}
        for ri, region in enumerate(regions):
            # regions are ccw in mcb
            region.reverse()
            r = [region[-2]]
            r.extend(region)
            r.append(region[1])
            for i in range(len(region) - 1):
                edge = r[i + 1], r[i + 2]
                if edge[0] not in node_edge:
                    node_edge[edge[0]] = edge
                if edge[1] not in node_edge:
                    node_edge[edge[1]] = edge
                start_c[edge] = r[i], r[i + 1]
                end_cc[edge] = r[i + 2], r[i + 3]
                right_polygon[edge] = ri
                twin = edge[1], edge[0]
                left_polygon[twin] = ri
                start_cc[twin] = end_cc[edge]
                end_c[twin] = start_c[edge]
            region_edge[ri] = edge


        # Test for holes
        # Need to add

        #lp = right_polygon[20,24] # for now just assign as placeholder
        #left_polygon[26,25] = lp
        #left_polygon[25,27] = lp
        #left_polygon[27,26] = lp

        # Edges belonging to a minimum cycle at this point without a left
        # region have external bounding polygon as implicit left poly. Assign this
        # explicitly
        rpkeys = right_polygon.keys() # only minimum cycle regions have explicit right polygons
        noleft_poly = [k for k in rpkeys if k not in left_polygon]

        for edge in noleft_poly:
            left_polygon[edge] = ri+1
        # Fill out s_c, s_cc, e_c, e_cc pointers for each edge (before filaments are added)
        regions = region_edge.keys()

        # Find the union of adjacent faces/regions
        unions = []
        while noleft_poly:
            path =[]
            current = noleft_poly.pop()
            path_head = current[0]
            tail = current[1]
            path.append(current)
            while tail != path_head:
                candidates = [ edge for edge in noleft_poly if edge[0] == tail ]
                j=0
                if len(candidates) > 1:
                    # we want candidate that forms largest ccw angle from current
                    angles = []
                    origin = pos[current[1]]
                    x0 = pos[current[0]][0] - origin[0]
                    y0 = pos[current[0]][1] - origin[1]
                    maxangle = 0.0
                    v0 = (x0,y0)

                    for i,candidate in enumerate(candidates):
                        x1 = pos[candidate[1]][0] - origin[0]
                        y1 = pos[candidate[1]][1] - origin[1]
                        v1 = (x1,y1)
                        v0_v1 = _angle(v0, v1)
                        if v0_v1 > maxangle:
                            maxangle = v0_v1
                            j=i
                        angles.append(v0_v1)

                next_edge = candidates[j]
                path.append(next_edge)
                noleft_poly.remove(next_edge)
                tail = next_edge[1]
            unions.append(path)


        # unions has the paths that trace out the unions of contiguous regions (in cw order)


        # Walk around each union in cw fashion
        # start_cc[current] = prev
        # end_c[current] = next
        for union in unions:
            for prev, edge in enumerate(union[1:-1]):
                start_cc[edge] = union[prev]
                end_c[edge] = union[prev+2]
            start_cc[union[0]] = union[-1]
            end_c[union[0]] = union[1]
            end_c[union[-1]] = union[0]
            start_cc[union[-1]] = union[-2]

        # after this find the holes in the external polygon (these should be the connected components)

        # Fill out s_c, s_cc, e_c, e_cc pointers for each edge after filaments are inserted

        regions = [set(region) for region in mcb['regions']]
        filaments = mcb['filaments']
        filament_region = {}
        for f, filament in enumerate(filaments):
            filament_region[f] = []
            #print "Filament: ", filament
            # set up pointers on filament edges prior to insertion
            ecc, ec, scc, sc, node_edge = self.filament_pointers(filament, node_edge)
            end_cc.update(ecc)
            start_c.update(sc)
            start_cc.update(scc)
            end_c.update(ec)

            # find which regions the filament is incident to
            sf = set(filament)
            incident_nodes = set()
            incident_regions = set()
            for r, region in enumerate(regions):
                internal = False
                sfi = sf.intersection(region)
                while sfi:
                    incident_nodes.add(sfi.pop())
                    incident_regions.add(r)

            while incident_nodes:
                incident_node = incident_nodes.pop()
                incident_links = self._filament_links_node(incident_node,node_edge, start_c, end_c)

                #Polar coordinates centered on incident node, no rotation from x-axis
                origin = coords_org[incident_node]

                #Logic: If the filament has 2 nodes, grab the other one
                # If the filament has 3+, grab the first and last segments
                if filament.index(incident_node) == 0:
                    f = filament[1]
                elif filament.index(incident_node) == 1:
                    f = filament[0]
                else:
                    f = filament[-2]
                filament_end = coords_org[f]
                #print "Filament:{}, Incident_Node:{} ".format(f, incident_node)
                #Determine the relationship between the origin and the filament end
                filamentx = filament_end[0] - origin[0]
                filamenty = filament_end[1] - origin[1]
                filament_theta = math.atan2(filamenty, filamentx) * 180 / math.pi
                if filament_theta < 0:
                    filament_theta += 360
                #Find the rotation necessary to get the filament to theta 0
                f_rotation = 360 - filament_theta

                link_angles = {}
                for link in incident_links:
                    if link[0] == incident_node:
                        link_node = link[1]
                    else:
                        link_node = link[0]
                    #Get the end coord of the incident link
                    link_node_coords = coords_org[link_node]
                    y = link_node_coords[1] - origin[1]
                    x = link_node_coords[0] - origin[0]
                    r = math.sqrt(x**2 + y**2)
                    node = coords_org[link_node]
                    node_theta = math.atan2(y, x) * 180 / math.pi
                    if node_theta < 0:
                        node_theta += 360
                    #Rotate the edge node to match the new polar axis
                    node_theta += f_rotation
                    if node_theta > 360:
                        node_theta -= 360
                    link_angles[link] = node_theta

                #Get the bisected edges
                ccwise = min(link_angles, key=link_angles.get)
                cwise = max(link_angles, key=link_angles.get)
                #Fix the direction of the bisected edges
                if ccwise.index(incident_node) != 1:
                    ccwise = (ccwise[1], ccwise[0])
                if cwise.index(incident_node) != 1:
                    cwise = (cwise[1], cwise[0])
                #Update the filament pointer in the direction (segment end, incident node)
                end_c[(f, incident_node)] = (cwise[1], cwise[0])
                end_cc[(f, incident_node)] = (ccwise[1], ccwise[0])
                #Reverse the edge direction
                start_c[(incident_node, f)] = (tuple(cwise))
                start_cc[(incident_node, f)] = (tuple(ccwise))
                #Update the bisected edge points in the direction(segment end, incident node)
                #Cwise link
                end_cc[cwise] = (incident_node, f)
                start_cc[(cwise[1],cwise[0])] = (incident_node, f)
                #CCWise link
                start_c[(ccwise[1], ccwise[0])] = (incident_node, f)
                end_c[ccwise] = (incident_node, f)
                #Now we need to update the right and left polygon for the filament.
                for r in incident_regions:
                     poly = ps.cg.Polygon([coords_org[v] for v in regions[r]])
                     if poly.contains_point((coords_org[filament[1]]) or pr.contains_point(coords_org[filament[0]])):
                            for n in range(len(filament)-1):
                                right_polygon[(filament[n], filament[n+1])] = r
                                left_polygon[(filament[n], filament[n+1])] = r
                                right_polygon[(filament[n+1], filament[n])] = r
                                left_polygon[(filament[n+1], filament[n])] = r

                #print "For filament {}: ".format((incident_node, f))
                #print "    CCW Most edge is {}".format(ccwise)
                #print "    CW Most edge is {}".format(cwise)







            '''
            if incident_regions:
                for r in incident_regions:
                    poly_region = ps.cg.Polygon([coords_org[v] for v in regions[r]])
                    print poly_region
            '''
            """
                if sfi:
                    node = sfi.pop()
                    filament_region[f].append(r)
                    #print "Region: ",filament_region[f]
                    # The logic here is that, if the filament is internal to the
                    # region we are good to go.  If it is external to the region it
                    # will never break and we are good to go.  If the filament is
                    # internal to one region and external to one or mroe regions,
                    # it will set the pointers incorrectly until it hits the
                    # internal region.  Then it sets the pointers based on the
                    # internal region and breaks.
                    region = []
                    for v in regions[r]:
                        region.append(coords_org[v])
                    pr = ps.cg.Polygon(region)
                    #print filament, filament[1]
                    if pr.contains_point(coords_org[filament[1]]) or pr.contains_point(coords_org[filament[0]]):
                        #print "Internal: ", r, filament
                        internal = True
                    # find edges in region that that are adjacent to sfi
                    # find which pair of edges in the region that the filament bisects
                    if mcb['regions'][r].count(node) == 2:
                        e1 = node, mcb['regions'][r][-2]
                        e2 = node, mcb['regions'][r][1]
                    else:
                        i = mcb['regions'][r].index(node)
                        e1 = node, mcb['regions'][r][i - 1]
                        e2 = node, mcb['regions'][r][i + 1]
                    # get filament edge
                    fi = filament.index(node)
                    fstart = True # start of filament is adjacent node to region
                    if filament[-1] == filament[fi]:
                        filament.reverse() # put end node at tail of list
                        fstart = False # end of filament is adjacent node to region
                    fi = 0
                    fj = 1
                    A = vertices[e1[1]]
                    B = vertices[e1[0]]
                    C = vertices[filament[fj]]
                    area_abc = A[0] * (B[1] - C[1]) + B[0] * (C[1] - A[1]) + C[0] * (A[1] - B[1])
                    D = vertices[e2[0]]
                    E = vertices[e2[1]]
                    area_dec = D[0] * (E[1] - C[1]) + E[0] * (C[1] - D[1]) + C[0] * (D[1] - E[1])

                    if area_abc < 0 and area_dec < 0:
                        # inside a region
                        end_cc[e1[1],e1[0]] = filament[fi],filament[fj]
                        start_c[e2] = filament[fi],filament[fj]
                        start_c[filament[fi],filament[fj]] = e1[1],e1[0]
                        start_cc[filament[fi],filament[fj]] = e2
                        right_polygon[filament[fi],filament[fj]] = r
                        left_polygon[filament[fi],filament[fj]] = r
                        right_polygon[filament[fj], filament[fi]] = r
                        left_polygon[filament[fj], filament[fi]] = r
                        end_cc[filament[fj], filament[fi]] = e2 # twin of first internal edge so enumerate region works

                        n_f = len(filament) - 1 # number of filament edges
                        for j in range(1, n_f):
                            sj = j
                            ej = j + 1
                            right_polygon[filament[sj], filament[ej]] = r
                            left_polygon[filament[sj], filament[ej]] = r
                            right_polygon[filament[ej], filament[sj]] = r
                            left_polygon[filament[ej], filament[sj]] = r
                        #last edge
                        right_polygon[filament[-1], filament[-2]] = r
                        left_polygon[filament[-1], filament[-2]] = r
                        right_polygon[filament[-2], filament[-1]] = r
                        left_polygon[filament[-2], filament[-1]] = r

                    else:
                        #print 'outside', filament[fi], filament[fj
                        end_c[e1[1],e1[0]] = filament[fi],filament[fj]
                        start_cc[e2] = filament[fi],filament[fj]
                        start_cc[filament[fi],filament[fj]] = e1[1],e1[0]
                        start_c[filament[fi],filament[fj]] = e2

                        n_f = len(filament) - 1 # number of filament edges
                        for j in range(1,n_f):
                            sj = j
                            ej = j + 1
                            start_c[filament[sj],filament[ej]] = filament[sj-1], filament[sj]
                            start_cc[filament[sj],filament[ej]] = filament[sj-1], filament[sj]
                            end_c[filament[sj-1], filament[sj]] = filament[sj],filament[ej]
                            end_cc[filament[sj-1], filament[sj]] = filament[sj],filament[ej]

                        # last edge
                        end_c[filament[-2],filament[-1]] = filament[-2],filament[-1]
                        end_cc[filament[-2],filament[-1]] = filament[-2],filament[-1]

                if internal is True:
                    break
            """
        self.start_c = start_c
        self.start_cc = start_cc
        self.end_c = end_c
        self.end_cc = end_cc
        self.region_edge = region_edge
        self.node_edge = node_edge
        self.right_polygon = right_polygon
        self.left_polygon = left_polygon
        self.start_node = start_node
        self.end_node = end_node
        self.node_coords = coords_org



    @staticmethod
    def filament_pointers(filament, node_edge={}):
        """
        Define the edge pointers for a filament


        Arguments
        ---------

        filament:   list
                    ordered nodes defining a graph filament where a filament is
                    defined as a sequence of ordered nodes with at least one
                    internal node having incidence=2

        node_edge:  dict
                    key is a node, value is the edge the node is assigned to

        Returns
        -------

        ecc:    dict
                key is edge, value is first edge encountered when rotating
                counterclockwise around edge start end node

        ec:     dict
                key is edge, value is first edge encountered when rotating
                clockwise around edge start end node


        scc:    dict
                key is edge, value is first edge encountered when rotating
                counterclockwise around edge start node


        sc:     dict
                key is edge, value is first edge encountered when rotating
                clockwise around edge start node

        node_edge: dict
                key is a node, value is the edge the node is assigned to

        """

        nv = len(filament)
        ec = {}
        ecc = {}
        sc = {}
        scc = {}
        for i in range(nv - 2):
            s0 = filament[i]
            e0 = filament[i + 1]
            s1 = filament[i + 2]
            ecc[s0, e0] = e0, s1
            ecc[s1, e0] = e0, s0
            ec[s0, e0] = e0, s1
            sc[e0, s1] = s0, e0
            scc[e0, s1] = s0, e0
            if s0 not in node_edge:
                node_edge[s0] = s0, e0
            if e0 not in node_edge:
                node_edge[e0] = s0, e0
            if s1 not in node_edge:
                node_edge[s1] = e0, s1
        # wrapper pointers for first and last edges
        ecc[filament[-2], filament[-1]] = filament[-1], filament[-2]
        ec[filament[-2], filament[-1]] = filament[-2], filament[-1]
        ecc[filament[1], filament[0]] = filament[0], filament[1]
        ec[filament[1], filament[0]] = filament[1], filament[0]
        sc[filament[0], filament[1]] = filament[0], filament[1]
        # technically filaments have to have at least intermediate node with incidence 2
        # if there is a single edge it isn't a filament, but we handle it here just in case
        # since the "first" edge not be treated in the for loop (which isn't entered)
        if nv == 2:
            sc[filament[0], filament[1]] = filament[0], filament[1]
            ec[filament[0], filament[1]] = filament[0], filament[1]
            ecc[filament[0], filament[1]] = filament[1], filament[0]
            scc[filament[0], filament[1]] = filament[0], filament[1]
            if filament[0] not in node_edge:
                node_edge[filament[0]] = filament[0], filament[1]
            if filament[1] not in node_edge:
                node_edge[filament[1]] = filament[0], filament[1]
        return ecc, ec, scc, sc, node_edge

    @staticmethod
    def regions_from_graph(nodes, edges, remove_holes=False):
        """
        Extract regions from nodes and edges of a planar graph

        Arguments
        ---------

        nodes: dict
            vertex id as key, coordinates of vertex as value

        edges: list
            (head,tail), (tail, head) edges

        Returns
        ------

        regions: list
                lists of nodes defining a region. Includes the external region

        filaments:  list
                    lists of nodes defining filaments and isolated vertices



        Examples
        --------
        >>> vertices = {0: (1, 8), 1: (1, 7), 2: (4, 7), 3: (0, 4), 4: (5, 4), 5: (3, 5), 6: (2, 4.5), 7: (6.5, 9), 8: (6.2, 5), 9: (5.5, 3), 10: (7, 3), 11: (7.5, 7.25), 12: (8, 4), 13: (11.5, 7.25), 14: (9, 1), 15: (11, 3), 16: (12, 2), 17: (12, 5), 18: (13.5, 6), 19: (14, 7.25), 20: (16, 4), 21: (18, 8.5), 22: (16, 1), 23: (21, 1), 24: (21, 4), 25: (18, 3.5), 26: (17, 2), 27: (19, 2)}
        >>> edges = [(1, 2),(1, 3),(2, 1),(2, 4),(2, 7),(3, 1),(3, 4),(4, 2),(4, 3),(4, 5),(5, 4),(5, 6),(6, 5),(7, 2),(7, 11),(8, 9),(8, 10),(9, 8),(9, 10),(10, 8),(10, 9),(11, 7),(11, 12),(11, 13),(12, 11),(12, 13),(12, 20),(13, 11),(13, 12),(13, 18),(14, 15),(15, 14),(15, 16),(16, 15),(18, 13),(18, 19),(19, 18),(19, 20),(19, 21),(20, 12),(20, 19),(20, 21),(20, 22),(20, 24),(21, 19),(21, 20),(22, 20),(22, 23),(23, 22),(23, 24),(24, 20),(24, 23),(25, 26),(25, 27),(26, 25),(26, 27),(27, 25),(27, 26)]
        >>> r = WED.regions_from_graph(vertices, edges)
        >>> r['filaments']
        [[6, 5, 4], [2, 7, 11], [14, 15, 16]]
        >>> r['regions']
        [[3, 4, 2, 1, 3], [9, 10, 8, 9], [11, 12, 13, 11], [12, 20, 19, 18, 13, 12], [19, 20, 21, 19], [22, 23, 24, 20, 22], [26, 27, 25, 26]]

        Notes
        -----
        Based on
        Eberly http://www.geometrictools.com/Documentation/MinimalCycleBasis.pdf.
        """

        def adj_nodes(start_key, edges):
            """Finds all nodes adjacent to start_key.

            Parameters
            ----------
            start_key: int
                The id of the node to find neighbors of.

            edges: list
                All edges in the graph

            Returns
            -------
            vnext: list
                List of adjacent nodes.
            """
            start_key
            vnext = []
            for edge in edges:
                if edge[0] == start_key:
                    vnext.append(edge[1])
            if len(vnext) == 0:
                pass
                #print "Vertex is end point."
            return vnext

        def find_start_node(nodes, node_coord):
            start_node = []
            minx = float('inf')
            for key, node in nodes.items():
                if node[0] <= minx:
                    minx = node[0]
                    start_node.append(key)
            if len(start_node) > 1:
                miny = float('inf')
                for i in range(len(start_node)):
                    if nodes[i][1] < miny:
                        miny = nodes[i][1]
                    else:
                        start_node.remove(i)
            return nodes[start_node[0]], node_coord[nodes[start_node[0]]]

        def clockwise(nodes, vnext, start_key, v_prev, vertices=None):
            v_curr = np.asarray(nodes[start_key])
            v_next = None
            if v_prev is None:
                v_prev = np.asarray([0, -1]) #This should be a vertical tangent to the start node at initialization.
            else:
                pass
            d_curr = v_curr - v_prev

            for v_adj in vnext:
                #No backtracking
                if np.array_equal(np.asarray(nodes[v_adj]),v_prev) == True:
                    continue
                if type(v_prev) == int:
                    if v_adj == v_prev:
                        continue
                #The potential direction to move in
                d_adj = np.asarray(nodes[v_adj]) - v_curr
                #Select the first candidate
                if v_next is None:
                    v_next = np.asarray(nodes[v_adj])
                    d_next = d_adj
                    convex = d_next[0]*d_curr[1] - d_next[1]*d_curr[0]
                    if convex <= 0:
                        convex = True
                    else:
                        convex = False
                #Update if the next candidate is clockwise of the current clock-wise most
                if convex is True:
                    if (d_curr[0]*d_adj[1] - d_curr[1]*d_adj[0]) < 0 or (d_next[0]*d_adj[1]-d_next[1]*d_adj[0]) < 0:
                        v_next = np.asarray(nodes[v_adj])
                        d_next = d_adj
                        convex = d_next[0]*d_curr[1] - d_next[1]*d_curr[0]
                        if convex <= 0:
                            convex = True
                        else:
                            convex = False
                else:
                    if (d_curr[0]*d_adj[1] - d_curr[1]*d_adj[0]) < 0 and (d_next[0]*d_adj[1]-d_next[1]*d_adj[0]) < 0:
                        v_next = np.asarray(nodes[v_adj])
                        d_next = d_adj
                        convex = d_next[0]*d_curr[1] - d_next[1]*d_curr[0]
                        if convex <= 0:
                            convex = True
                        else:
                            convex = False
            prev_key = start_key
            if vertices == None:
                return tuple(v_next.tolist()), node_coord[tuple(v_next.tolist())], prev_key
            else:
                return tuple(v_next.tolist()), vertices[tuple(v_next.tolist())], prev_key
        def counterclockwise(nodes, vnexts, start_key, prev_key):
            v_next = None
            v_prev = np.asarray(nodes[prev_key])
            v_curr = np.asarray(nodes[start_key])
            d_curr = v_curr - v_prev

            for v_adj in vnexts:
                #Prohibit Back-tracking
                if v_adj == prev_key:
                    continue
                d_adj = np.asarray(nodes[v_adj]) - v_curr

                if v_next == None:
                    v_next = np.asarray(nodes[v_adj])
                    d_next = d_adj
                    convex = d_next[0]*d_curr[1] - d_next[1]*d_curr[0]

                if convex <= 0:
                    if d_curr[0]*d_adj[1] - d_curr[1]*d_adj[0] > 0 and d_next[0]*d_adj[1] - d_next[1]*d_adj[0] > 0:
                        v_next = np.asarray(nodes[v_adj])
                        d_next = d_adj
                        convex = d_next[0]*d_curr[1] - d_next[1]*d_curr[0]
                    else:
                        pass
                else:
                    if d_curr[0]*d_adj[1] - d_curr[1]*d_adj[0] > 0 or d_next[0]*d_adj[1]-d_next[1]*d_adj[0] > 0:
                        v_next = np.asarray(nodes[v_adj])
                        d_next = d_adj
                        convex = d_next[0]*d_curr[1] - d_next[1]*d_curr[0]
                    else:
                        pass
            prev_key = start_key
            try:
                return tuple(v_next.tolist()), node_coord[tuple(v_next.tolist())], prev_key
            except:
                return v_next, None, prev_key
        def remove_edge(v0,v1,edges, ext_edges):
            try:
                ext_edges.append((v0,v1))
                ext_edges.append((v1,v0))
                edges.remove((v0,v1))
                edges.remove((v1,v0))
            except:
                pass
            return edges, ext_edges

        def remove_heap(v0,sorted_nodes):
            sorted_nodes[:] = [x for x in sorted_nodes if x[0] != v0]
            return sorted_nodes

        def remove_node(v0, nodes, nodes_coord, vertices):
            vertices[v0] = nodes[v0]
            del nodes_coord[nodes[v0]]
            del nodes[v0]
            return nodes, nodes_coord, vertices

        def extractisolated(nodes,node_coord,v0,primitives, vertices, ext_edges):
            primitives.append(v0)
            nodes, node_coord, vertices = remove_node(v0, nodes, node_coord, vertices)
            return nodes, node_coord, primitives, vertices, ext_edges

        def extractfilament(v0,v1, nodes, node_coord,sorted_nodes, edges, primitives,cycle_edge, vertices, ext_edges, iscycle=False):
            if (v0,v1) in cycle_edge or (v1,v0) in cycle_edge:
                iscycle = True
            if iscycle == True:
            #This deletes edges that are part of a cycle, but does not add them as primitives.
                if len(adj_nodes(v0,edges)) >= 3:
                    edges, ext_edges = remove_edge(v0,v1,edges, ext_edges)
                    v0 = v1
                    if len(adj_nodes(v0, edges)) == 1:
                        v1 = adj_nodes(v0, edges)[0]
                while len(adj_nodes(v0, edges)) == 1:
                    v1 = adj_nodes(v0, edges)[0]
                    #Here I need to do the cycle check again.
                    iscycle = False
                    if (v0,v1) in cycle_edge or (v1,v0) in cycle_edge:
                        iscycle = True

                    if iscycle == True:
                        edges, ext_edges = remove_edge(v0,v1,edges, ext_edges)
                        nodes, node_coord, vertices = remove_node(v0, nodes, node_coord, vertices)
                        sorted_nodes = remove_heap(v0, sorted_nodes)
                        v0 = v1
                    else:
                        break
                if len(adj_nodes(v0, edges)) == 0:

                    nodes, node_coord, vertices = remove_node(v0, nodes, node_coord, vertices)
                    sorted_nodes = remove_heap(v0, sorted_nodes)
            else:
                #Filament found
                primitive = []
                if len(adj_nodes(v0,edges)) >= 3:
                    primitive.append(v0)
                    edges, ext_edges = remove_edge(v0,v1,edges, ext_edges)
                    v0 = v1
                    if len(adj_nodes(v0, edges)) == 1:
                        v1 = adj_nodes(v0, edges)[0]

                while len(adj_nodes(v0, edges)) == 1:
                    primitive.append(v0)
                    v1 = adj_nodes(v0, edges)[0]
                    sorted_nodes = remove_heap(v0, sorted_nodes)
                    edges, ext_edges = remove_edge(v0, v1, edges, ext_edges)
                    nodes, node_coord, vertices = remove_node(v0, nodes, node_coord, vertices)
                    v0 = v1

                primitive.append(v0)
                if len(adj_nodes(v0, edges)) == 0:

                    sorted_nodes = remove_heap(v0, sorted_nodes)
                    edges, ext_edges = remove_edge(v0, v1, edges, ext_edges)
                    nodes, node_coord, vertices = remove_node(v0, nodes, node_coord, vertices)
                primitives.append((primitive))

            return sorted_nodes, edges, nodes, node_coord, primitives, vertices, ext_edges

        def extract_primitives(start_key,sorted_nodes, edges, nodes, node_coord, primitives,minimal_cycles,cycle_edge, vertices, ext_edges):
            v0 = start_key
            visited = []
            sequence = []
            sequence.append(v0)

            #Find the CWise most vertex
            vnext = adj_nodes(start_key, edges)
            start_node,v1,v_prev = clockwise(nodes,vnext,start_key,prev_key)
            v_curr = v1
            v_prev = v0
            #Find minimal cycle using CCWise rule
            process = True
            if v_curr == None:
                process = False
            elif v_curr == v0:
                process = False
            elif v_curr in visited:
                process = False

            while process == True:
                sequence.append(v_curr)
                visited.append(v_curr)
                vnext = adj_nodes(v_curr, edges)

                v_curr_coords,v_next,v_prev = counterclockwise(nodes,vnext,v_curr, v_prev)
                v_curr = v_next
                if v_curr == None:
                    process = False
                elif v_curr == v0:
                    process = False
                elif v_curr in visited:
                    process = False

            if v_curr is None:
                #Filament found, not necessarily at start_key
                sorted_nodes, edges, nodes, node_coord, primitives, vertices, ext_edges = extractfilament(v_prev, adj_nodes(v_prev, edges)[0],nodes, node_coord, sorted_nodes, edges, primitives, cycle_edge, vertices, ext_edges)

            elif v_curr == v0:
                #Minimal cycle found
                primitive = []
                iscycle=True
                sequence.append(v0)
                minimal_cycles.append(list(sequence))
                #Remove the v0, v1 edges from the graph.
                edges, ext_edges = remove_edge(v0,v1,edges, ext_edges)
                sorted_nodes = remove_heap(v0, sorted_nodes)#Not in pseudo-code, but in source.
                #Mark all the edges as being part of a minimal cycle.
                if len(adj_nodes(v0, edges)) == 1:
                    cycle_edge.append((v0, adj_nodes(v0, edges)[0]))
                    cycle_edge.append((adj_nodes(v0, edges)[0], v0))
                    sorted_nodes, edges, nodes, node_coord, primitives, vertices, ext_edges = extractfilament(v0, adj_nodes(v0, edges)[0],nodes, node_coord, sorted_nodes, edges, primitives,cycle_edge, vertices, ext_edges)
                if len(adj_nodes(v1, edges)) == 1:
                    cycle_edge.append((v1, adj_nodes(v1, edges)[0]))
                    cycle_edge.append((adj_nodes(v1, edges)[0],v1))
                    sorted_nodes, edges, nodes, node_coord, primitives, vertices, ext_edges = extractfilament(v1, adj_nodes(v1, edges)[0],nodes, node_coord, sorted_nodes, edges, primitives, cycle_edge, vertices, ext_edges)

                for i,v in enumerate(sequence[1:-1]):
                    cycle_edge.append((v,sequence[i]))
                    cycle_edge.append((sequence[i],v))

            else:
                #vcurr was visited earlier, so traverse the filament to find the end
                while len(adj_nodes(v0,edges)) == 2:
                    if adj_nodes(v0,edges)[0] != v1:
                        v1 = v0
                        v0 = adj_nodes(v0,edges)[0]
                    else:
                        v1 = v0
                        v0 = adj_nodes(v0, edges)[1]
                sorted_nodes, edges, nodes, node_coord, primitives, vertices, ext_edges = extractfilament(v0,v1,nodes, node_coord, sorted_nodes, edges, primitives,cycle_edge,vertices,ext_edges)

            return sorted_nodes, edges, nodes, node_coord, primitives, minimal_cycles,cycle_edge, vertices, ext_edges
        #1.
        sorted_nodes = sorted(nodes.iteritems(), key=operator.itemgetter(1))
        node_coord = dict (zip(nodes.values(),nodes.keys()))

        #2.
        primitives = []
        minimal_cycles = []
        cycle_edge = []
        prev_key = None #This is only true for the first iteration.
        #This handles edge and node deletion we need populated later.
        vertices = {}
        ext_edges = []

        #3.
        while sorted_nodes: #Iterate through the sorted list
            start_key = sorted_nodes[0][0]
            numadj = len(adj_nodes(start_key, edges))

            if numadj == 0:
                nodes, node_coord, primitives, vertices, ext_edges = extractisolated(nodes,node_coord,start_key,primitives, vertices, ext_edges)
                sorted_nodes.pop(0)
            elif numadj == 1:
                sorted_nodes, edges, nodes, node_coord, primitives, vertices, ext_edges = extractfilament(start_key, adj_nodes(start_key, edges)[0],nodes, node_coord, sorted_nodes, edges,primitives,cycle_edge, vertices, ext_edges)
            else:
                sorted_nodes, edges, nodes, node_coord, primitives, minimal_cycles,cycle_edge, vertices, ext_edges = extract_primitives(start_key,sorted_nodes, edges, nodes, node_coord, primitives, minimal_cycles,cycle_edge, vertices, ext_edges)

        #4. Remove holes from the graph
        if remove_holes == True:
            polys = []
            for cycle in minimal_cycles:
                polys.append(ps.cg.Polygon([ps.cg.Point(vertices[pnt]) for pnt in cycle]))

            pl = ps.cg.PolygonLocator(polys)

            # find all overlapping polygon mbrs
            overlaps ={}
            nump = len(minimal_cycles)
            for i in range(nump):
                overlaps[i] = pl.overlapping(polys[i].bounding_box)

            # for overlapping mbrs (left,right) check if right polygon is contained in left
            holes = []
            for k in overlaps:
                for  pc in overlaps[k]:
                    s = sum( [polys[k].contains_point(v) for v in pc.vertices])
                    if s == len(pc.vertices):
                        # print k, pc
                        holes.append((k,pc))

            for hole in holes:
                outer, inner = hole
                inner = polys.index(inner)
                minimal_cycles.pop(inner)

        #5. Remove isolated vertices
        filaments = []
        for index, primitive in enumerate(primitives):
            if type(primitive) == list:
                filaments.append(primitive)

        results = {}
        results['regions'] = minimal_cycles
        results['filaments'] = filaments
        results['vertices'] = vertices
        results['edges'] = ext_edges
        results['nodes'] = vertices
        return results

    @classmethod
    def wed_from_json(cls,infile, binary=True):
        wed = WED()
        if binary:
            with open(infile, 'r') as f:
                data = cPickle.load(f)
        else:
            with open(infile, 'r') as f:
                data = json.loads(f)

        wed.start_c = {ast.literal_eval(key):value for key, value in data['start_c'].iteritems()}
        wed.start_cc = {ast.literal_eval(key):value for key, value in data['start_cc'].iteritems()}
        wed.end_c = {ast.literal_eval(key):value for key, value in data['end_c'].iteritems()}
        wed.end_cc = {ast.literal_eval(key):value for key, value in data['end_cc'].iteritems()}
        wed.region_edge = {ast.literal_eval(key):value for key, value in data['region_edge'].iteritems()}
        wed.node_edge = {ast.literal_eval(key):value for key, value in data['node_edge'].iteritems()}
        wed.right_polygon = {ast.literal_eval(key):value for key, value in data['right_polygon'].iteritems()}
        wed.left_polygon = {ast.literal_eval(key):value for key, value in data['left_polygon'].iteritems()}
        wed.start_node = {ast.literal_eval(key):value for key, value in data['start_node'].iteritems()}
        wed.end_node = {ast.literal_eval(key):value for key, value in data['end_node'].iteritems()}
        wed.node_coords = {ast.literal_eval(key):value for key, value in data['node_coords'].iteritems()}
        wed.edge_list = data['edge_list']

        return wed

    def wed_to_json(self, outfile, binary=True):
        #keys need to be strings
        new_wed = {}
        for key, value in vars(self).iteritems():
            nested_attr = {}
            if isinstance(value, dict):
                for k2, v2 in value.iteritems():
                    nested_attr[str(k2)] = v2
                new_wed[key] = nested_attr
            else:
                new_wed[key] = value
        #print new_wed['edge_list']
        if binary:
            with open(outfile, 'w') as outfile:
                outfile.write(cPickle.dumps(new_wed, 1))
        else:
            with open(outfile, 'w') as outfile:
                json_str = json.dumps(new_wed, sort_keys=True, indent=4)
                outfile.write(json_str)


    def nearest_point_on_edge(self,v1):
        """
        Computes the distance from the start_node of point observation
         tagged to an edge. Okabe 3.3.3.8 (pg.65)
        """
        pass


    def lisa(self, points):
        """
        This is a wrapper that gets points observations snapped to the WED
         and then performs LISA analysis.

        Parameters
        ----------
        points: list or ndarray
            A list of PySAL Points to snap to the WED

        attributes: list of ndarray
            The attribute value of the observation.
            Assumed to be in the same position as the
             corresponding geometry

        Returns
        -------
        LISA : Object
            A PySAL LISA object
        """

        #This mapping has double edges, but the W is single.
        # We need to maintain dimensionality for LISA to work
        mapping = self.assign_points_to_edges(points)
        #Generate the W object
        w = self.w_links()
        #Generate the observation count
        y = np.zeros(len(w.neighbors))
        for index, value in enumerate(w.neighbors):
            obs_at_edge = mapping[value]
            #rate
            y[index] = len(obs_at_edge)
        lisa = ps.Moran_Local(y, w)
        return lisa

    def moran(self, y, w):
        """
        This is a wrapper that gets points observations snapped to the WED
         and then performs LISA analysis.

        Parameters
        ----------
        points: list or ndarray
            A list of PySAL Points to snap to the WED

        attributes: list of ndarray
            The attribute value of the observation.
            Assumed to be in the same position as the
             corresponding geometry

        Returns
        -------
        moran : Object
            A PySAL Moran's I`s object
        """

        #Generate the observation count and link it back
        # to the correct edge position in the W
        y_matched = np.zeros(len(w.neighbors))
        for index, value in enumerate(w.neighbors):
            obs_at_edge = y[value]
            #rate
            y_matched[index] = len(obs_at_edge)
        moran = ps.Moran(y_matched, w)
        return moran

    def edge_length(self):
        """
        Compute the cartesian length of all edges.  This is a helper
         function to allow for ratio data with spatial autocorrelation
         analysis.

        Parameters
        ----------
        None

        Returns
        -------
        length : dict {tuple(edge): float(length)}
            The length of each edge.
        """

        lengths = {}
        for edge in self.edge_list:
            lengths[edge] = get_points_dist(self.node_coords[edge[0]],
                                            self.node_coords[edge[1]])
        return lengths

    def assign_points_to_nodes(self, pts):
        #Setup a dictionary that stores node_id:[observations values]
        obs_to_node = {}
        for x in self.node_coords.iterkeys():
            obs_to_node[x] = set()

        #Generate a KDTree of all of the nodes in the wed
        kd_tree = KDTree([node for node in self.node_coords.itervalues()])

        #Iterate over each observation and query the KDTree.
        for index, point in enumerate(pts):
            nn = kd_tree.query(point, k=1)
            obs_to_node[nn[1]].add(attribs[index])

        return obs_to_node


    def assign_points_to_edges(self,points):
        """
        Assigns point observations to network edges

        Arguments
        ---------

        pts: (list) PySAL point objects or tuples of x,y coords

        Returns
        -------

        obs_to_edge: (dict) where key is the edge and value is the observation index.

        Notes
        -----
        Assumes double edges and sets observations to both edges, e.g. [2,0] and [0,2]
        Wrapped in a try / except block incase the edges are single .
        """
        #We can't enumerate over an array of points, so convert to list.
        if not isinstance(points, list):
            pts = points.tolist()
        else:
            pts = points

        #Empty dict with all the edges
        obs_to_edge = {}
        for e in self.edge_list:
            obs_to_edge[e] = set()

        #Build PySAL polygon objects from each region
        polys = {}
        for r in range(len(self.region_edge)):
            edges = self.enum_edges_region(r)
            poly = []
            for e in edges:
                poly.append(Point(self.node_coords[e[0]]))
            polys[r] = (Polygon(poly))

        #Brute force check point in polygon
        for pt_index, pt in enumerate(pts):
            for key, poly in polys.iteritems():
                internal = False
                if ps.cg.standalone.get_polygon_point_intersect(poly, pt):
                    internal = True
                    potential_edges = self.enum_edges_region(key)[:-1]
                    #Flags
                    dist = np.inf
                    e = None
                    #Brute force check all edges of the region
                    for edge in potential_edges:
                        seg = LineSegment(self.node_coords[edge[0]], self.node_coords[edge[1]])
                        ndist = ps.cg.standalone.get_segment_point_dist(seg, pt)[0]
                        if ndist < dist:
                            e = edge
                            dist = ndist
                    obs_to_edge[e].add(pt_index)
                    try:
                        obs_to_edge[e[1], e[0]].add(pt_index)
                    except:
                        pass
                    break
            #Exceptionally brute force - if we aren't in a poly, check all edges
            # added to test how this functions, must be optimized.
            if internal == False:
                #The point is not internal to a polygon.  Now we need to
                # brute force check against all of the unshared edges.
                # Shared edges are known to be internal, so we can skip them.
                dist = np.inf
                e = None
                for edge in self.edge_list:
                    seg = LineSegment(self.node_coords[edge[0]], self.node_coords[edge[1]])
                    ndist = ps.cg.standalone.get_segment_point_dist(seg, pt)[0]
                    if ndist < dist:
                        e = edge
                        dist = ndist
                obs_to_edge[e].add(pt_index)
                try:
                    obs_to_edge[e[1], e[0]].add(pt_index)
                except:
                    pass

        return obs_to_edge

if __name__ == '__main__':
    #Best way to add calls to the doctests in the tests directory?
    pass

###########Redundant or Unused?#################

"""
def connected_component(adjacency, node):

    Find the connected component that a node belongs to

    Arguments
    ---------

    adjacency: (dict) key is a node, value is a list of adjacent nodes

    node: id of node

    Returns
    -------

    visited: list of nodes comprising the connected component containing node

    Notes
    -----
    Relies on a depth first search of the graph

    A = copy.deepcopy(adjacency)
    if node not in A:
        # isolated node
        return [node]
    stack = [node]
    visited = []
    searching = True
    visited.append(node)
    while searching:
        current = stack[-1]
        if A[current]:
            child = A[current].pop()
            if child not in visited:
                visited.append(child)
                stack.append(child)
        else:
            stack.remove(current)
            if not stack:
                searching = False
    return visited


def connected_components(adjacency):

    Find all the connected components in a graph

    Arguments
    ---------
    adjacency: dict
               key is a node, value is a list of adjacent nodes

    Returns
    -------

    components: list of lists for connected components

    nodes = adjacency.keys()
    components = []
    while nodes:
        start = nodes.pop()
        component = connected_component(adjacency, start)
        if len(component) > 1:
            for node in component:
                if node in nodes:
                    nodes.remove(node)
        components.append(component)
    return components
"""

