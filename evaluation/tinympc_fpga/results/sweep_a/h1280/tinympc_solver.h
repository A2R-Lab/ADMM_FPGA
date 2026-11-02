#ifndef TINYMPC_SOLVER_H
#define TINYMPC_SOLVER_H

#define NX 12
#define NU 4
#define N 1281
#define N_MINUS_1 1280
#define MAX_ITER 10

// Memory layout constants
#define X0_OFFSET 0
#define XREF_OFFSET 12
#define UREF_OFFSET 15384
#define X_OUT_OFFSET 20504
#define U_OUT_OFFSET 35876

#define MAIN_MEMORY_SIZE 40996

typedef float data_t;

// Main IP core interface
void tinympc_solver(
    data_t main_memory[MAIN_MEMORY_SIZE]
);

// Sub-function declarations
void forward_pass(
    data_t x[N][NX],
    data_t u[N_MINUS_1][NU],
    data_t d[N_MINUS_1][NU]
);

void backward_pass(
    data_t d[N_MINUS_1][NU],
    data_t p[N][NX],
    data_t q[N][NX],
    data_t r[N_MINUS_1][NU]
);

void update_slack(
    data_t znew[N_MINUS_1][NU],
    data_t vnew[N][NX],
    data_t u[N_MINUS_1][NU],
    data_t x[N][NX],
    data_t y[N_MINUS_1][NU],
    data_t g[N][NX],
    data_t u_min[N_MINUS_1][NU],
    data_t u_max[N_MINUS_1][NU],
    data_t x_min[N][NX],
    data_t x_max[N][NX]
);

void update_dual(
    data_t y[N_MINUS_1][NU],
    data_t g[N][NX],
    data_t u[N_MINUS_1][NU],
    data_t x[N][NX],
    data_t znew[N_MINUS_1][NU],
    data_t vnew[N][NX]
);

void update_linear_cost(
    data_t r[N_MINUS_1][NU],
    data_t q[N][NX],
    data_t p[N][NX],
    data_t Uref[N_MINUS_1][NU],
    data_t Xref[N][NX],
    data_t znew[N_MINUS_1][NU],
    data_t vnew[N][NX],
    data_t y[N_MINUS_1][NU],
    data_t g[N][NX]
);

bool check_termination(
    data_t x[N][NX],
    data_t vnew[N][NX],
    data_t v[N][NX],
    data_t u[N_MINUS_1][NU],
    data_t znew[N_MINUS_1][NU],
    data_t z[N_MINUS_1][NU]
);

#endif