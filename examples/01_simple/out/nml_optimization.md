# MHM optimization namelist

All relevant configurations for the optimization parameters of MHM.
This namelist corresponds to the `optimization` section in the MHM configuration.


**Namelist**: `optimization`

## Fields

| Name | Type | Required | Info |
| --- | --- | --- | --- |
| `name` | string | no | Optimization name |
| `niterations` | integer | yes | Number of iterations |
| `tolerance` | real | yes | Convergence tolerance |
| `seed` | integer | no | Random seed |
| `dds_r` | real | no | DDS perturbation rate |
| `mcmc_opti` | logical | no | MCMC optimization |
| `mcmc_error_params` | real array | no | MCMC error parameters per domain |

## Field details

### `name` - Optimization name

Name for the optimization run.

Summary:
- Type: `character(len=buf)`
- Required: no
- Examples: `'test_optimization'`

### `niterations` - Number of iterations

Number of iterations for the optimization algorithm

Summary:
- Type: `integer`
- Required: yes
- Examples: `100`

### `tolerance` - Convergence tolerance

Tolerance for convergence of the optimization algorithm.

Summary:
- Type: `real`
- Required: yes

### `seed` - Random seed

Random seed for reproducibility. Use -9 for random seed.

Summary:
- Type: `integer(i4)`
- Required: no
- Default: `-9`

### `dds_r` - DDS perturbation rate

Parameter for the DDS algorithm controlling the perturbation rate.

Summary:
- Type: `real(dp)`
- Required: no
- Default: `0.2`

### `mcmc_opti` - MCMC optimization

Whether to perform MCMC optimization.

Summary:
- Type: `logical`
- Required: no
- Default: `.true.`

### `mcmc_error_params` - MCMC error parameters per domain

Parameters for the MCMC error model: err = a + b+Q

Summary:
- Type: `real(dp), dimension(2, max_iter)`
- Required: no
- Default: `[0.01, 0.6, 0.2, 0.3]` (repeated, order: C)

## Examples

```fortran
&optimization
  name = 'test_optimization'
  niterations = 100
  tolerance = 0.0
  seed = -9
  dds_r = 0.2
  mcmc_opti = .true.
  mcmc_error_params(1, :) = 0.01, 0.6, 0.2, 0.3
/
```

