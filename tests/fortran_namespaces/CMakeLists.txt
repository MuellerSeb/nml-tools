cmake_minimum_required(VERSION 3.20)
project(generated_namespaces LANGUAGES Fortran)

set(CMAKE_Fortran_STANDARD 2008)
set(CMAKE_Fortran_STANDARD_REQUIRED ON)

add_executable(generated_namespaces
  application_types.f90
  conformance.f90
  out/nml_helper.f90
  out/nml_namespaces.f90
  out/nml_wrapper_status.f90
  out/f2py_wrapper_status.f90
)
