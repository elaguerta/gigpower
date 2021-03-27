# Elaine Laguerta (github: @elaguerta)
# LBNL GIG
# File created: 19 February 2021
# Create Solution superclass

from . circuit import Circuit
from . volt_var_controller import VoltVARController
from typing import Iterable
import opendssdirect as dss

import re
import numpy as np
import pandas as pd


class Solution():

    # class variables set for all SolutionNR3 instances
    # TODO: If any of these need to be set by instance, move into self.__init__
    SLACKIDX = 0  # assume slack bus is at index 0

    # TODO: VSLACK the same for all objects. Write a SETVSLACK method on the class.
    VSLACK = np.array([1, np.exp(1j*-120*np.pi/180), np.exp(1j*120*np.pi/180)])
    # TODO: check if we need V0 and I0 on the class. 
    # They seem like internal variables for nr3
    V0, I0 = None, None
    maxiter = 100

    # standardize solution parameter name, index values, columns, and 
    # datatypes across the class
    # see self._init_solution_matrices
    SOLUTION_PARAMS = {
        'V': ['buses', ['A', 'B', 'C'], complex],
        'I': ['lines', ['A', 'B', 'C'], complex],
        'sV': ['buses', ['A', 'B', 'C'], complex]}

    # TODO: Make a 'solution.set_tolerance()' method
    
    def __init__(self, dss_fp: str):
        """
        sets up a Solution object with a pointer to a Circuit mapped from opendss
        Solutions keep a pointer to the dss object used to map the Circuit
        """
        #  setup calls to opendss----------------------------------------------
        self.dss = dss  # save dss instance to object
        dss.run_command('Redirect ' + dss_fp)
        dss.Solution.Solve()  # solve first for base values
        # set zip values for all Solutions and all Circuits
        dss.Solution.Solve()  # solve again to set zip values on dss

        #  map Circuit and vvc objects-----------------------------------------
        self.circuit = Circuit(dss)
        self.volt_var_controllers = self.parse_vvc_objects(dss_fp)

        #  initialize solution parameters---------------------------------------
        self.iterations = 0
        # stores the tolerance at most recent completed iteration
        self.solution_tolerance = -1
        # stores the final value of Vtest - Vref at convergence
        self.convergence_diff = -1  
        self._init_solution_matrices()

        # Voltage parameters. TODO: are these only for fbs?
        # If so, move to solution_fbs.py
        self.Vtest = np.zeros(3, dtype='complex')

    def _init_solution_matrices(self):
        """
        Initializes matrices to store solution values in ndarrays as follows:
        V: num_buses x 3, complex pu voltage, by bus index
        I: num_lines x 3, complex pu current phasors, by line index
        Inode: num_buses x 3, complex pu current phasors delivered to bus, by bus index
        Stx: num_lines x 3, line transmitting end power, by line index
        Srx: num_lines x 3, line receiving end power, by line index
        sV: num_buses x 3, total powers at each bus, by bus index
        """
        for param in self.__class__.SOLUTION_PARAMS:
            element_group, cols, datatype = self.__class__.SOLUTION_PARAMS[param]
            if element_group == 'lines':  # include transformers and vrs
                num_rows = self.circuit.get_total_lines()
            else:
                num_rows = getattr(getattr(self.circuit, element_group), 'num_elements')
            setattr(self, param, np.zeros((num_rows, len(cols)), dtype=datatype))

    def get_data_frame(self, param: str) -> pd.DataFrame:
        """
        Returns a DataFrame for the specified solution paramater.
        param: must be in SOLUTION_PARAMS
        """
        try:
            element_group, cols, data_type = self.__class__.SOLUTION_PARAMS.get(param)
            index = getattr(self.circuit, element_group).all_names()
            if element_group == 'lines':  # include transformers and vrs
                index += self.circuit.transformers.all_names()
                index += self.circuit.voltage_regulators.all_names()
            data = getattr(self, param)
            return pd.DataFrame(data=data, index=index, columns=cols, dtype=data_type)
        except KeyError:
            print(f"Not a valid solution parameter. Valid parameters: \
                  {self.__class__.SOLUTION_PARAMS.keys()}")

    def parse_vvc_objects(self, fn: str):
        """ From 20180601/PYTHON/lib/dss_vvc.py by @kathleenchang"""
        # Parse VVC lines in DSS file
        vvarobjects = []
        f = open(fn, "r")

        for l in f:
            if re.findall('(?i)New VVC', l):
                bp = []

                # array of VVC breakpoints
                breakpoints = str.split(re.findall(r"(?i)BP=\s*([^\n\r]*)", l)[0], ',')

                for elem in breakpoints:
                    point = re.findall("[0-9.]*",  elem)
                    for i in point:
                        if i:
                            bp.append(float(i))
                print(bp)

                # zero-indexed phase, is one-indexed in DSS file
                phase = int(re.findall('(?i)phase=\s*([0-9]*)', l)[0]) - 1
                print(phase)

                minkvar = float(re.findall('(?i)min_kvar=([-0-9]*)', l)[0])
                print(minkvar)

                maxkvar = float(re.findall('(?i)max_kvar=([-0-9]*)', l)[0])
                print(maxkvar)

                bus = re.findall(r"(?i)bus=([\w.]*)\s", l)[0]
                bus = re.findall(r"[\w]*", bus)[0]
                print(bus)

                # create volt var object
                voltvarobject = VoltVARController(bp, minkvar, maxkvar, bus, phase)
                vvarobjects.append(voltvarobject)
                print("\n --------------")

        for e in vvarobjects:
            print(e)
        return vvarobjects

    def volt_var_control(self):
        print('hi')

    def regulator_ldc_control(self):
        nnode = self.circuit.buses.num_elements
        nline = self.circuit.lines.num_elements
        vr_lines = self.circuit.voltage_regulators.get_num_lines_x_ph
        tf_lines = self.circuit.transformers.get_num_lines_x_ph
        XNR = self.XNR

        vr_idx_dict = voltage_regulator_index_dict()
        vr_line_idx = range(0, vr_lines)

        # flag if need to rerun NR3
        flag = 0
        vr_line_counter = 0
        XNR_final = XNR

        for k in vr_idx_dict.keys():
            # {bus: [indices in dss.RegControls.AllNames(), ...]}
            for vridx in vr_idx_dict[k]:

                dss.RegControls.Name(dss.RegControls.AllNames()[vridx])
                dss.Circuit.SetActiveBus(
                    dss.CktElement.BusNames()[0].split(".")[0])
                winding = dss.RegControls.Winding()

                Vbase = dss.Bus.kVBase() * 1000
                Sbase = 10**6
                Ibase = Sbase / Vbase
                band = dss.RegControls.ForwardBand()
                target_voltage = dss.RegControls.ForwardVreg()

                idxbs = dss.Circuit.AllBusNames().index(
                    (dss.CktElement.BusNames()[0].split('.')[0]))

                ph = dss.CktElement.BusNames()[0].split('.')[1:]
                ph_arr = [0, 0, 0]
                for i in ph:
                    ph_arr[int(i) - 1] = 1
                if len(ph) == 0:
                    ph_arr = [1, 1, 1]
                for ph in range(len(ph_arr)):
                    if ph_arr[ph] == 1:  # loop over existing phases of voltage regulator

                        NR_voltage = np.abs((XNR[2*nnode*ph + 2*idxbs] + (
                            1j * XNR[2*nnode*ph + 2*idxbs + 1])) * Vbase / dss.RegControls.PTRatio())

                        if dss.RegControls.ForwardR() and dss.RegControls.ForwardX() and dss.RegControls.CTPrimary():
                            # if LDC exists

                            #vr_line_counter - counts the number of lines passed; two lines for every phase
                            #vridx - index of current voltage regulator in dss.RegControls.AllNames()
                            #tf_lines - number of transformers

                            line_idx = 2 * \
                                vr_line_idx[vr_line_counter] + 2*(winding - 1)

                            I_reg = XNR[2*3*(nnode+nline) + 2*tf_lines + line_idx] + \
                                1j * XNR[2*3*(nnode+nline) + 2 *
                                         tf_lines + line_idx + 1]

                            V_drop = (dss.RegControls.ForwardR(
                            ) + 1j*dss.RegControls.ForwardX()) / 0.2 * (I_reg * Ibase / dss.RegControls.CTPrimary())

                            V_drop = (dss.RegControls.ForwardR() + 1j*dss.RegControls.ForwardX()) / 0.2 * (
                                I_reg * Ibase / (dss.RegControls.CTPrimary()/0.2))
                            V_R = np.abs(NR_voltage - V_drop)

                            abs_diff = np.abs(V_R - target_voltage)
                            V_compare = V_R
                            print('vcompare', dss.RegControls.Name(), V_compare)

                        else:
                            # if LDC term does not exist
                            print('**** LDC missing term ***** ')
                            abs_diff = np.abs(NR_voltage - target_voltage)
                            V_compare = NR_voltage

                        print('absolute difference: ', abs_diff, "\n")
                        vr_line_counter += 1

                        # compare NR3 voltage to forward Vreg voltage +- band
                        if abs_diff <= band:  # converges
                            XNR_final = XNR
                            continue

                        elif abs_diff > band:
                            # NR3 voltage above forward-Vreg
                            if V_compare > (target_voltage + band):
                                if dss.RegControls.TapNumber() <= -16:
                                    print('Tap Number Out of Bounds')
                                    XNR_final = XNR

                                else:
                                    print('Decrease Tap Number')
                                    dss.RegControls.TapNumber(
                                        dss.RegControls.TapNumber() - 1)
                                    print('New tap number ',
                                          dss.RegControls.TapNumber())
                                    flag = 1  # run NR3 again
                            else:  # NR3 voltage below forward-Vreg
                                if dss.RegControls.TapNumber() >= 16:
                                    print('Tap Number Out of Bounds')
                                    print('New tap number ',
                                          dss.RegControls.TapNumber())
                                    XNR_final = XNR

                                else:
                                    print('Increase tap number')
                                    dss.RegControls.TapNumber(
                                        dss.RegControls.TapNumber() + 1)
                                    flag = 1  # run NR3 again
            if flag == 1:
                return flag, XNR_final
        return flag, XNR_final

    def get_bus_powers(self):
        """
        Total complex powers by bus (load powers and capacitor powers)
        indexed by bus 
        """
        return self.get_load_powers() + self.get_capacitor_powers()

    def calc_Stx(self):
        tx_bus_matrix = self.circuit.get_tx_idx_matrix()
        self.Stx = self.V[tx_bus_matrix] * np.conj(self.I)
    
    def calc_Srx(self):
        rx_bus_matrix = self.circuit.get_rx_idx_matrix()
        self.Stx = self.V[rx_bus_matrix] * np.conj(self.I)

    def calc_Inode(self) -> None:
        """ Calculate self.Inode (currents consumed at each node) """
        # for node in self.network.get_nodes():
        #     node_V = self.V[node.name]
        #     node_sV = self.sV[node.name]
        #     node_I = np.conj(np.divide(node_sV, node_V))
        #     self.Inode[node.name] = mask_phases(node_I, (3,), node.phases)
        pass

    def VMag_df(self):
        """
        returns VMag as a dataframe indexed by node name
        """
        V = self.V_df()
        return V.applymap(lambda cmplx_v: (np.real(cmplx_v)**2 + np.imag(cmplx_v)**2) ** .5)

    def params_df(self):
        """
        returns solution paramaters as a dataframe
        """
        index = ['iterations', 'Vtest', 'Vref', 'tolerance', 'diff']
        data = [self.iterations, self.Vtest,
                self.Vref, self.tolerance, self.diff]
        return pd.DataFrame(data, index).transpose()

    def getLoadPowers(self):
        """
        Return total load powers by bus, calculated from solved V value
        per node.
        """
        data = np.zeros((len(self.network.nodes), 3), dtype=complex)

        for bus_name, bus_idx in self.network.bus_idx_dict.items():
            node = self.network.nodes[bus_name]
            data[bus_idx] = calc_load_power(node, self.V[bus_name])

        return pd.DataFrame(data, self.network.bus_idx_dict.keys(), ['A', 'B', 'C'])

    def getCapPowers(self):
        """
        Return total cap powers by bus, calculated from solved V value
        per node.
        """
        data = np.zeros((len(self.network.nodes), 3), dtype=complex)

        for bus_name, bus_idx in self.network.bus_idx_dict.items():
            node = self.network.nodes[bus_name]
            data[bus_idx] = calc_cap_power(node, self.V[bus_name])

        return pd.DataFrame(data, self.network.bus_idx_dict.keys(), ['A', 'B', 'C'])

    def nomNodePwrs_df(self):
        """
        One time calculation of total nominal node power based on solved V
        equivalent to aP = 1, aI = aQ = 0
        """

        # s = spu.*(aPQ + aI.*(abs(V)) + aZ.*(abs(V)).^2) - 1j * cappu + wpu

        data = np.zeros((len(self.network.nodes), 3), dtype=complex)

        for node in self.network.get_nodes():
            node_idx = self.network.bus_idx_dict[node.name]
            nodeV = np.ones((3,), dtype=complex)
            data[node_idx] += calc_total_node_power(
                node, nodeV, [0, 0, 1, 0, 0, 1])
        return pd.DataFrame(data, self.network.bus_idx_dict.keys(), ['A', 'B', 'C'])

    def print_solution(self):
        """
        prints solution to stdout
        """
        print("\n Parameters:")
        print(self.params_df())

        print("\n V solution")
        print(self.V_df())

        print("\n I solution")
        print(self.I_df())

        print("\n Inode solution")
        print(self.Inode_df())

        print("\n Stx solution")
        print(self.Stx_df())

        print("\n Srx solution")
        print(self.Srx_df())

        print("\n sV solution")
        print(self.sV_df())
        print()
