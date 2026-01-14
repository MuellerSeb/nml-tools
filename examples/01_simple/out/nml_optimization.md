# MHM optimization schema

All relevant configurations for the optimization parameters of MHM

**Namelist**: `optimization`

## Fields

| Name | Type | Required | Info |
| --- | --- | --- | --- |
| name | string | no | Optimization name |
| niterations | integer | yes | Number of iterations |
| tolerance | real | yes | Convergence tolerance |
| seed | integer | no | Random seed |
| dds_r | real | no | DDS perturbation rate |
| mcmc_opti | logical | no | MCMC optimization |
| mcmc_error_params | real array | no | MCMC error parameters per domain |

## Field details

### `name` - Optimization name

Name for the optimization run.

|  |  |
| --- | --- |
| Type | `character(len=50)` |
| Required | no |

### `niterations` - Number of iterations

Number of iterations for the optimization algorithm

|  |  |
| --- | --- |
| Type | `integer(i4)` |
| Required | yes |

### `tolerance` - Convergence tolerance

Tolerance for convergence of the optimization algorithm.

|  |  |
| --- | --- |
| Type | `real(dp)` |
| Required | yes |

### `seed` - Random seed

Random seed for reproducibility. Use -9 for random seed.

|  |  |
| --- | --- |
| Type | `integer(i4)` |
| Required | no |
| Default | `-9_i4` |

### `dds_r` - DDS perturbation rate

Parameter for the DDS algorithm controlling the perturbation rate.

|  |  |
| --- | --- |
| Type | `real(dp)` |
| Required | no |
| Default | `0.2_dp` |

### `mcmc_opti` - MCMC optimization

Whether to perform MCMC optimization.

|  |  |
| --- | --- |
| Type | `logical` |
| Required | no |
| Default | `.true.` |

### `mcmc_error_params` - MCMC error parameters per domain

Parameters for the MCMC error model: err = a + b+Q

|  |  |
| --- | --- |
| Type | `real(dp), dimension(2, 3)` |
| Required | no |
| Default | `reshape([0.01_dp, 0.6_dp], shape=[2, 3], pad=[0.01_dp, 0.6_dp])` |

