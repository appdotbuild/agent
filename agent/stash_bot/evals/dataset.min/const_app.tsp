model PhysicalConstant {
    name: string;
    symbol: string;
    value: decimal;
    unit: string;
    uncertainty: decimal;
    description: string;
}

model ConstantRelation {
    sourceConstants: PhysicalConstant[];
    targetConstant: PhysicalConstant;
    formula: string;
}

model CalculationRequest {
    sourceConstants: PhysicalConstant[];
    targetConstant: string;
}

interface FundamentalConstantsBot {
    @llm_func(2)
    calculateConstant(request: CalculationRequest): PhysicalConstant;

    @llm_func(1)
    listAvailableConstants(): PhysicalConstant[];

    @llm_func(1)
    getConstantDetails(name: string): PhysicalConstant;

    @llm_func(2)
    findConstantRelations(constantName: string): ConstantRelation[];
}