# Optimization configurations

All relevant configurations for the optimization parameters.

**Namelist**: `optimization`

## Fields

| Name | Type | Required | Info |
| --- | --- | --- | --- |
| [name](#name) | string | no | Optimization name |
| [method](#method) | string | yes | Optimization method |
| [try_methods](#try_methods) | string array | no | Try alternative methods |
| [complex_sizes](#complex_sizes) | integer array | no | Complex sizes for SCE |
| [niterations](#niterations) | integer | yes | Number of iterations |
| [tolerance](#tolerance) | real | yes | Convergence tolerance |
| [seed](#seed) | integer | no | Random seed |
| [dds_r](#dds_r) | real | no | DDS perturbation rate |
| [mcmc_opti](#mcmc_opti) | logical | no | MCMC optimization |
| [mcmc_error_params](#mcmc_error_params) | real array | yes | MCMC error parameters per iteration |
| [include_parameters](#include_parameters) | logical array | no | Include parameters |

## Field details

### name

Optimization name `name`

Name for the optimization run.

Summary:
- Type: `character(len=buf)`
- Required: no
- Examples: `"test_optimization"`

### method

Optimization method `method`

Optimization algorithm to be used.

Summary:
- Type: `character(len=buf)`
- Required: yes
- Allowed values: `"DDS"`, `"MCMC"`, `"SCE"`

### try_methods

Try alternative methods `try_methods`

Whether to try alternative optimization methods if the primary fails.

Summary:
- Type: `character(len=buf), dimension(3)`
- Required: no
- Allowed values: `"DDS"`, `"MCMC"`, `"SCE"`
- Examples: `["MCMC", "DDS", "SCE"]`

### complex_sizes

Complex sizes for SCE `complex_sizes`

Sizes of complexes for the SCE optimization method.

Summary:
- Type: `integer(i4), dimension(3)`
- Required: no
- Allowed values: `5`, `10`, `15`, `20`, `30`
- Examples: `[5, 10, 15]`

### niterations

Number of iterations `niterations`

Number of iterations for the optimization algorithm

Summary:
- Type: `integer(i4)`
- Required: yes
- Minimum: `>= 10`
- Examples: `100`

### tolerance

Convergence tolerance `tolerance`

Tolerance for convergence of the optimization algorithm.

Summary:
- Type: `real(dp)`
- Required: yes
- Minimum: `> 0.0`
- Examples: `0.001`

### seed

Random seed `seed`

Random seed for reproducibility. Use -9 for random seed.

Summary:
- Type: `integer(i4)`
- Required: no
- Default: `-9`

### dds_r

DDS perturbation rate `dds_r`

Parameter for the DDS algorithm controlling the perturbation rate.

Summary:
- Type: `real(dp)`
- Required: no
- Default: `0.2`
- Minimum: `> 0.0`

### mcmc_opti

MCMC optimization `mcmc_opti`

Whether to perform MCMC optimization.

Summary:
- Type: `logical`
- Required: no
- Default: `.true.`

### mcmc_error_params

MCMC error parameters per iteration `mcmc_error_params`

Parameters for the MCMC error model

Summary:
- Type: `real(dp), dimension(3, 2, max_iter)`
- Flexible tail dims: 2
- Required: yes
- Minimum: `>= 0.0`
- Examples: `[0.01, 0.6, 0.2]`

### include_parameters

Include parameters `include_parameters`

List of parameter indices to include in the optimization.

Summary:
- Type: `logical, dimension(3)`
- Required: no
- Default: `.true.`
- Examples: `[.true., .false., .true.]`

## Example

```fortran
&optimization
  name = "test_optimization"
  method = "DDS"
  try_methods(:) = "MCMC", "DDS", "SCE"
  complex_sizes(:) = 5, 10, 15
  niterations = 100
  tolerance = 0.001
  seed = -9
  dds_r = 0.2
  mcmc_opti = .true.
  mcmc_error_params(:, 1, 1) = 0.01, 0.6, 0.2
  include_parameters(:) = .true., .false., .true.
/
```

