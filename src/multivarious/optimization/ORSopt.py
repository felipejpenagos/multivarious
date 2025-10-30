# orsopt.py
# -----------------------------------------------------------------------------
# Optimized Step Size Random Search (ORSopt)
# Translation of Henri P. Gavin's ORSopt.m (Duke CEE).
# Depends on: optim_options(), box_constraint(), avg_cov_func()
# -----------------------------------------------------------------------------

from __future__ import annotations
import time
import numpy as np

from multivarious.utils.optim_options import optim_options
from multivarious.utils.box_constraint import box_constraint
from multivarious.utils.avg_cov_func import avg_cov_func



def orsopt(func, x_init, x_lb=None, x_ub=None, options_in=None, consts=1.0):
    """
    Optimized Step Size Random Search (inequality constraints via penalties).

    Parameters
    ----------
    func : callable
        Signature: f, g = func(x, consts).  f is scalar, g is (m,) constraints (g<0 feasible).
        x is in *original* units (not scaled).
    x_init : array-like (n,)
        Initial guess.
    x_lb, x_ub : array-like (n,), optional
        Lower/upper bounds on x. If omitted, wide bounds are used (±1e2*|x_init|).
    options_in : array-like, optional
        See optim_options() for the 19 parameters (same positions as MATLAB).
    consts : any
        Passed through to `func`.

    Returns
    -------
    x_opt : np.ndarray (n,)
    f_opt : float
    g_opt : np.ndarray (m,)
    cvg_hst : np.ndarray (n+5, k)
        Columns store [x; f; max(g); func_count; cvg_x; cvg_f] per iteration.
    """

    # ----- options & inputs -----
    x_init = np.asarray(x_init, dtype=float).flatten()
    n = x_init.size

    if x_lb is None or x_ub is None:
        x_lb = -1.0e2 * np.abs(x_init)
        x_ub = +1.0e2 * np.abs(x_init)
    x_lb = np.asarray(x_lb, dtype=float).flatten()
    x_ub = np.asarray(x_ub, dtype=float).flatten()

    options = optim_options(options_in)
    msglev    = int(options[0])   # display level
    tol_x     = float(options[1]) # design var convergence tol
    tol_f     = float(options[2]) # objective convergence tol
    tol_g     = float(options[3]) # constraint tol
    max_evals = int(options[4])   # budget
    # options[5], [6] handled inside avg_cov_func
    find_feas = bool(options[9])  # stop once feasible

    # ----- scale to [-1, +1] (as in MATLAB) -----
    s0 = (x_lb + x_ub) / (x_lb - x_ub)
    s1 = 2.0 / (x_ub - x_lb)
    x1 = s0 + s1 * x_init
    x1 = np.clip(x1, -1.0, 1.0)

    # book-keeping
    function_count = 0
    iteration = 1
    cvg_hst = np.full((n + 5, max(1, max_evals)), np.nan)
    fa = np.zeros(4)  # augmented costs for up to 4 evaluations
    BX = 1           # enforce bounds inside avg_cov_func

    # ----- analyze initial guess -----
    fv, gv, x1, cJ, nAvg = avg_cov_func(func, x1, s0, s1, options, consts, BX)
    function_count += nAvg
    if not np.isscalar(fv):
        raise ValueError("Objective returned by func(x,consts) must be a scalar.")
    gv = np.atleast_1d(gv).astype(float).flatten()

    # initial records
    f_opt = float(fv)
    x_opt = x1.copy()
    g_opt = gv.copy()

    cvg_x = 1.0
    cvg_f = 1.0
    cvg_hst[:, iteration - 1] = np.concatenate([(x_opt - s0) / s1,
                                                [f_opt, np.max(g_opt), function_count, cvg_x, cvg_f]])

    # search parameters
    sigma = 0.200  # step scale
    nu = 1.0       # exponent in sigma schedule
    t0 = time.time()

    # initialize four points (x1 already done)
    fa[0] = f_opt
    x2 = x1.copy(); g2 = g_opt.copy()
    x3 = x1.copy(); g3 = g_opt.copy()
    x4 = x1.copy(); g4 = g_opt.copy(); fa[3] = fa[0]

    last_update = function_count

    # ============================ main loop ============================
    while function_count < max_evals:
        # random direction
        r = sigma * np.random.randn(n)

        # +1 step
        a2, _ = box_constraint(x1, r)
        x2 = x1 + a2 * r
        fa2, g2, x2, c2, nAvg = avg_cov_func(func, x2, s0, s1, options, consts, BX)
        function_count += nAvg
        fa[1] = fa2

        # decide direction for second probe (+2 or -1)
        step = +2.0 if fa[1] < fa[0] else -1.0
        a3, _ = box_constraint(x1, step * r)
        x3 = x1 + a3 * step * r
        fa3, g3, x3, c3, nAvg = avg_cov_func(func, x3, s0, s1, options, consts, BX)
        function_count += nAvg
        fa[2] = fa3

        # fit local quadratic along r using (0, dx2, dx3)
        dx2 = np.linalg.norm(x2 - x1) / (np.linalg.norm(r) + 1e-16)
        dx3 = np.linalg.norm(x3 - x1) / (np.linalg.norm(r) + 1e-16)
        # regularization (i3 in MATLAB)
        i3 = 1e-9 * np.eye(3)
        A = np.array([[0.0,         0.0, 1.0],
                      [0.5*dx2**2,  dx2, 1.0],
                      [0.5*dx3**2,  dx3, 1.0]], dtype=float) + i3
        a, b, c = np.linalg.solve(A, fa[:3])

        quad_update = False
        if a > 0.0:
            d = -b / a  # zero-slope point
            a4, _ = box_constraint(x1, d * r)
            x4 = x1 + a4 * d * r
            fa4, g4, x4, c4, nAvg = avg_cov_func(func, x4, s0, s1, options, consts, BX)
            function_count += nAvg
            fa[3] = fa4
            quad_update = True

        # choose best of the four
        i_min = int(np.argmin(fa))
        if i_min == 0:
            pass
        elif i_min == 1:
            x1, g1, c1 = x2, g2, c2
        elif i_min == 2:
            x1, g1, c1 = x3, g3, c3
        else:
            x1, g1, c1 = x4, g4, c4

        if i_min > 0:
            # shrink scope as evaluations proceed
            sigma = sigma * (1.0 - function_count / max_evals)**nu
        x1 = np.clip(x1, -1.0, 1.0)

        # update incumbent if improved
        if fa[i_min] < f_opt:
            x_opt = x1.copy()
            f_opt = float(fa[i_min])
            g_opt = np.atleast_1d(g1).astype(float).flatten()

            # convergence metrics vs last recorded iteration
            prev = cvg_hst[:n, iteration - 1]
            prev_f = cvg_hst[n, iteration - 1]
            xx = (x_opt - s0) / s1
            cvg_x = (np.linalg.norm(prev - xx) /
                     (np.linalg.norm(xx) + 1e-16)) if iteration >= 1 and np.all(np.isfinite(prev)) else 1.0
            cvg_f = (abs(prev_f - f_opt) / (abs(f_opt) + 1e-16)) if iteration >= 1 and np.isfinite(prev_f) else 1.0

            last_update = function_count
            iteration += 1
            cvg_hst[:, iteration - 1] = np.concatenate([xx,
                                                        [f_opt, np.max(g_opt), function_count, cvg_x, cvg_f]])

            if msglev:
                elapsed = time.time() - t0
                rate = function_count / max(elapsed, 1e-9)
                remaining = max_evals - function_count
                eta_sec = int(remaining / max(rate, 1e-9))
                print(" -+-+-+-+-+-+-+-+-+-+- ORSopt -+-+-+-+-+-+-+-+-+-+-+-+-+")
                print(f" iteration                = {iteration:5d}   "
                      f"{'*** feasible ***' if np.max(g_opt) <= tol_g else '!!! infeasible !!!'}")
                print(f" function evaluations     = {function_count:5d} of {max_evals:5d}"
                      f" ({100.0*function_count/max_evals:4.1f}%)")
                print(f" e.t.a.                   = ~{eta_sec//60}m{eta_sec%60:02d}s")
                print(f" objective                = {f_opt:11.3e}")
                print(" variables                = " + " ".join(f"{v:11.3e}" for v in xx))
                print(f" max constraint           = {np.max(g_opt):11.3e}")
                print(f" Convergence F            = {cvg_f:11.4e}   tolF = {tol_f:8.6f}")
                print(f" Convergence X            = {cvg_x:11.4e}   tolX = {tol_x:8.6f}")
                print(" -+-+-+-+-+-+-+-+-+-+- ORSopt -+-+-+-+-+-+-+-+-+-+-+-+-+")

        # termination checks
        if np.max(g_opt) < tol_g and find_feas:
            if msglev:
                print("Woo Hoo! Feasible solution found — stopping as requested.")
            break

        if iteration > 1 and (cvg_x < tol_x or cvg_f < tol_f):
            if msglev:
                print("*** Converged solution found!")
                print(f"*** {'feasible' if np.max(g_opt) < tol_g else 'NOT feasible'}")
            break

    # time-out message
    if function_count >= max_evals and msglev:
        print(f"Enough! Max evaluations ({max_evals}) exceeded. "
              "Increase tol_x (options[1]) or max_evals (options[4]) and try again.")

    # scale back to original units
    x_init_out = (s0 + s1 * x_init - s0) / s1  # = x_init (kept for parity)
    x_opt_out = (x_opt - s0) / s1

    # print summary (compact)
    if msglev:
        dur = time.time() - t0
        print(f"*** Completion : objective = {f_opt:11.3e}   evals = {function_count}   "
              f"time = {dur:.2f}s")
        print("               x_init         x_lb          x_opt          x_ub")
        print("-----------------------------------------------------------------")
        for i in range(n):
            print(f"x({i+1:3d})  {x_init_out[i]:12.5f}  {x_lb[i]:12.5f}  {x_opt_out[i]:12.5f}  {x_ub[i]:12.5f}")
        print("*** Constraints:")
        for j, gj in enumerate(np.atleast_1d(g_opt).flatten(), 1):
            tag = " ** binding ** " if gj > -tol_g else ""
            if gj > tol_g:
                tag = " ** not ok ** "
            print(f"   g({j:3d}) = {gj:12.5f}{tag}")

    # finalize history
    # add a final column mirroring the last iteration, as in MATLAB ending
    k = max(1, iteration)
    out_hist = cvg_hst[:, :k].copy()
    if not np.isfinite(out_hist[-1, -1]):
        out_hist[-1, -1] = out_hist[-1, max(0, k-2)]

    return x_opt_out, f_opt, g_opt, out_hist

