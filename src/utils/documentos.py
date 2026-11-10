"""Validação de documentos (CPF/CNPJ) por dígito verificador.

Extraído do validador de CPF que já existia embutido em
`schemas.FuncionarioCreate` (mesmo algoritmo, sem mudança de
comportamento) para poder ser reaproveitado pelo cadastro de Fornecedor
(schemas.FornecedorInput), que precisa aceitar tanto CPF (fornecedor
pessoa física) quanto CNPJ (fornecedor pessoa jurídica) no mesmo campo.
"""

import re


def validar_cpf(cpf: str) -> str:
    """Valida um CPF por dígito verificador. Retorna só os dígitos (sem
    máscara) se válido, levanta ValueError caso contrário."""
    cpf = re.sub(r"\D", "", cpf)
    if len(cpf) != 11 or len(set(cpf)) == 1:
        raise ValueError("CPF inválido")
    for i in range(9, 11):
        soma = sum(int(cpf[j]) * (i + 1 - j) for j in range(i))
        if (soma * 10 % 11) % 10 != int(cpf[i]):
            raise ValueError("CPF inválido")
    return cpf


def validar_cnpj(cnpj: str) -> str:
    """Valida um CNPJ por dígito verificador. Retorna só os dígitos (sem
    máscara) se válido, levanta ValueError caso contrário."""
    cnpj = re.sub(r"\D", "", cnpj)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        raise ValueError("CNPJ inválido")

    def _digito(base: str, pesos: list) -> str:
        soma = sum(int(d) * p for d, p in zip(base, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _digito(cnpj[:12], pesos1)
    d2 = _digito(cnpj[:12] + d1, pesos2)
    if cnpj[-2:] != d1 + d2:
        raise ValueError("CNPJ inválido")
    return cnpj


def validar_cpf_ou_cnpj(documento: str) -> str:
    """Aceita tanto CPF (11 dígitos) quanto CNPJ (14 dígitos), usado no
    cadastro de Fornecedor (pode ser pessoa física ou jurídica)."""
    digitos = re.sub(r"\D", "", documento)
    if len(digitos) == 11:
        return validar_cpf(digitos)
    if len(digitos) == 14:
        return validar_cnpj(digitos)
    raise ValueError("Documento deve ser um CPF (11 dígitos) ou CNPJ (14 dígitos) válido")
