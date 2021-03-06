"""
A class for representing and solving Schrodinger's equaiton
"""

from __future__ import print_function

import numpy as np
from scipy.integrate import simps
from scipy import fftpack
import warnings
import collections


class Schrod:
    def __init__(self, x, V, n_basis=20):
        """
        Parameters
        ----------
        x : array_like, float
            Length-N array of evenly spaced spatial coordinates
        V : array_like, float
            Length-N array giving the potential at each x
        n_basis : int
            The number of square-well basis states used in the calculation (default=20)
        """

        # Set the inputs
        self.x = x
        self.V = V
        self.n_basis = n_basis

        # Validate the inputs
        N = self.x.size
        assert N > 1
        assert self.x.shape == (N,)
        assert (np.diff(x) >= 0).all()

        V_shape = self.V.shape
        V_shape_len = len(V_shape)
        assert V_shape_len == 1 or V_shape_len == 2
        if V_shape_len == 1:
            assert V_shape == (N,)
        elif V_shape_len == 2:
            assert V_shape[1] == N

        assert isinstance(n_basis, int)
        assert n_basis > 0

        # Set the derived quantities
        self._N = N
        self.dx = x[1] - x[0]
        self._x_min = x[0]
        self._x_max = x[-1]
        self.box_size = np.abs(self._x_max - self._x_min)
        self._x_center = self._x_min + self.box_size / 2.

        self.dk = 2 * np.pi / self.box_size
        self.k = -0.5 * (self._N-1) * self.dk + self.dk * np.arange(self._N)

        # Allocate memory for eigenvalues and eigenvectors
        self.eigs = np.zeros(shape=(V_shape[0], n_basis))
        self.vecs = np.zeros(shape=(V_shape[0], n_basis, n_basis))

    def solve(self, verbose=False):
        if verbose:
            print("Calculating the Hamiltonian matrices...")
        Hs = self._H(verbose)

        if verbose:
            print("Diagonalizing the Hamiltonian matrices...")

        self.eigs, self.vecs = np.linalg.eigh(Hs, UPLO='L')

    def solve_to_tol(self, n_eig, tol=1e-6, n_init=5, n_max=50, n_step=5, err_type = "max_mean", verbose=False):
        """
        Increase the basis size until the maximum change among the lowest
        <n_eig> eigenvalues is less than <tol>
        :param n_eig: The number of eigenvalues (lowest) to check for convergence.
        :param tol: The desired maximum relative error in the output
        :param n_init: The initial number of basis states. Must satisfy n_init >= n_eig
        :param n_max: The maximum number of basis states to include before stopping.
        :param n_step: The number of basis states added in each convergence test.
        :return: A tuple with the following information (A, B, C):
            A: Boolean. True if maximum measured relative error less than or equal to <tol>
            B: The number of basis states included when convergence reached.
            C: The measured relative error
        :param err_type: The type of error to calculate, one of
                    "max": the maximum error is no greater than :param tol:
                    "mean": the mean error is no greater than :param tol:
                    "max_mean" (default): the maximum of the mean error per eigenvalue is no greater than :param tol:
        :param verbose: bool, whether to print diagnostic information
        """

        # The initial truncation
        self.set_n_basis(n_init)
        self.solve()
        eigs = self.eigs[..., 0:n_eig]
        err = 1

        # The maximum relative error in the lowst <n_eig> eigenvalues
        measured_tol = 1  # the max rel. err. of the eigenvalues
        n = n_init
        passed = False
        while (not passed) and (n+n_step <= n_max):
            n += n_step

            self.set_n_basis(n)
            self.solve()
            eigs_new = self.eigs[..., 0:n_eig]

            err = np.abs((eigs - eigs_new) / 0.5 / (eigs + eigs_new))
            if err_type is "max":
                measured_tol = np.max(err)
            elif err_type is "mean":
                measured_tol = np.mean(err)
            elif err_type is "max_mean":
                measured_tol = np.max(np.mean(err, axis=0))
            else:
                warnings.warn("Invalid <err_type>. Must be one of 'max', 'mean' or 'max_mean'. Assuming 'max_mean'.")
                measured_tol = np.max(np.mean(err, axis=0))
            eigs = eigs_new

            if verbose:
                print("Number of basis states: %i \n Measured error: %.2e" % (n, measured_tol))

            if measured_tol <= tol:
                passed = True

        if not passed:
            warnings.warn("Unable to achieve desired tolerance of %.2e.\n"
                          "Achieved a tolerance of %.2e.\n"
                          "Try increasing the maximum number of basis states." % (tol, measured_tol))

        solution = collections.namedtuple('Solution',
                                          ['eig_errs', 'n_basis_converged', 'passed'])

        return solution(err, n, passed)

    def psi_eig_x(self):
        basis_vec = np.arange(1, self.vecs.shape[-1] + 1)

        return np.tensordot(self.vecs,
                      self._psi0(basis_vec, self.x), axes=(-2,0))

    def prob_eig_x(self):
        return self.psi_eig_x() ** 2

    def psi_tx(self, psi_0_x, t_vec):
        # Caculate the overlap of the initial wavefunction with all of the eigenstates
        psis = self.psi_eig_x()
        coeffs = simps(x=self.x, y=psi_0_x * psis, axis=-1)

        # Calculate the complex phases at each time
        phases = np.exp(-1j * np.outer(t_vec, self.eigs))

        # Calculate the wavefunction on the grid at each time slice
        psi_of_t = np.dot(phases * coeffs, psis)
        print(psi_of_t.shape)

        return psi_of_t

    def prob_tx(self, psi_0, t_vec):
        return np.absolute(self.psi_tx(psi_0, t_vec)) ** 2

    def psi_tk(self, psi_0, t_vec):
        psitx = self.psi_tx(psi_0,t_vec)

        psitk = fftpack.fft(psitx, overwrite_x=True)
        return fftpack.fftshift(psitk, axes=-1)

    def prob_tk(self, psi_0, t_vec):
        return np.absolute(self.psi_tk(psi_0, t_vec)) ** 2

    def expected_E(self, psi):
        integrand = -0.5 * np.conj(psi) * np.gradient(np.gradient(psi, self.dx, axis=-1), self.dx, axis=-1) + \
                    np.absolute(psi)**2 * self.V
        return np.real(simps(x=self.x, y=integrand, axis=-1))

    # Set functions
    def set_x(self, x):
        self.x = x
        self._x_min = x[0]
        self._x_max = x[-1]
        self.box_size = self._x_max = self._x_min
        self._x_center = self._x_min + self.box_size / 2.

    def set_V(self, V):
        self.V = V

    def set_n_basis(self, n_basis):
        self.n_basis = n_basis

    # Private functions:
    def _H(self, verbose=False):
        n_matels = self.n_basis * (self.n_basis + 1) / 2

        # initialize an empty hamiltonian(s)
        h=0

        if len(self.V.shape) is 2:
            h = np.zeros((self.V.shape[0], self.n_basis, self.n_basis))
        elif len(self.V.shape) is 1:
            h = np.zeros(( self.n_basis, self.n_basis))
        for m in range(self.n_basis):
            for n in range(m + 1):
                h[..., m, n] = self._Vmn(m, n)

                # Print a status
                n_sofar = (m + 1) * m / 2 + n + 1
                percent = n_sofar / n_matels * 100

                if verbose:
                    print("\r  Status: %0.2f %% complete" % percent, end='')

        if verbose:
            print("")

        return h + np.diag(self._E0(np.arange(1, self.n_basis + 1)))


    def _psi0(self, n, x):
        """
        Evaluate the nth box state at x
        :param n: array-like, 1-indexed state labels
        :param x: array-like, positions between -1 and 1
        :return: an array of shape (len(n), len(x))
        """
        kn = n * np.pi / self.box_size

        return np.sqrt(2 / self.box_size) * \
               np.sin(np.outer(kn, x - self._x_center + self.box_size / 2))

    def _E0(self, n):
        """
        The nth energy level in the box
        :param n: the state label
        :return: the energy
        """
        return n ** 2 * np.pi ** 2 / (2. * self.box_size ** 2)

    def _matel_integrand(self, m, n):
        """
        The n,m matrix element of the V potential evaluated at the x coordinates
        :param n:   the row index
        :param m:   the column index
        :param x:   array-like, a vector of x coordinates
        :param V:   array-like, an array of potential values. The rows correspond to
                    the entries in x. The columns correspond to different potentials
        :return:    the integrand of the matrix element
        """
        return self._psi0(m + 1, self.x) * self._psi0(n + 1, self.x) * self.V

    def _Vmn(self, m, n):
        return simps(x=self.x, y=self._matel_integrand(m, n), axis=-1)

if __name__ == "__main__":
    x = np.linspace(-1,1,10)
    V = 1/2 * x**2

    eqn = Schrod(x, V)
    print(eqn.k)

