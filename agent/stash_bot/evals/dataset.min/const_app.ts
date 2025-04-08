export interface PhysicalConstant {
    name: string;
    symbol: string;
    value: number;
    unit: string;
    uncertainty: number;
    description: string;
}

export interface ConstantRelation {
    sourceConstants: PhysicalConstant[];
    targetConstant: PhysicalConstant;
    formula: string;
}

export interface CalculationRequest {
    sourceConstants: PhysicalConstant[];
    targetConstant: string;
}

// Optional: Interface for the bot's methods
export interface FundamentalConstantsBot {
    calculateConstant(request: CalculationRequest): Promise<PhysicalConstant>;
    listAvailableConstants(): Promise<PhysicalConstant[]>;
    getConstantDetails(name: string): Promise<PhysicalConstant>;
    findConstantRelations(constantName: string): Promise<ConstantRelation[]>;
}