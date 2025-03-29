export function $llm_func(context, target, description) {
  const properties = target.parameters.node.properties;
  const property = properties[0];

  // get the fnHandler argument type
  const fnArgumentType = property.value.target.sv;

  // typespec models available
  const modelsMap = target.namespace.models;
  const keysIterator = modelsMap.keys();
  const keysArray = Array.from(keysIterator);

  // Check if the return type is void
  if (target.returnType && target.returnType.kind === "Intrinsic" && target.returnType.name === "void") {
    context.program.reportDiagnostic({
      code: 'llm-func-void-return',
      target: target,
      messageId: 'voidReturn',
      severity: 'error',
      message: `
       Function '${target.name}' must return a non-void value.
       
       <wrong-example>
        @llm_func(1)
        fnHandler(args: ArgumentsModel): void;
       </wrong-example>

       <correct-example>
        @llm_func(1)
        fnHandler(args: ArgumentsModel): boolean;
       </correct-example>
      `,
    });
  }

  // check if the argument type is a complex model type
  // else, report an error
  // we can't JSONify primitive types
  if (!keysArray.includes(fnArgumentType)) {
    context.program.reportDiagnostic({
      code: 'llm-func-invalid-argument',
      target: property.value.target,
      messageId: 'invalidArgument',
      severity: 'error',
      message: `
       Function '${target.name}' must use a complex model type as argument, found '${fnArgumentType}' instead.
       Extract the argument type into a model and use it as the argument type.

       <wrong-example>
        @llm_func(1)
        fnHandler(args: utcDateTime): void;
       </wrong-example>

       <correct-example>
        model ArgumentsModelName {
            date: utcDateTime;
        }
            
        @scenario("""
        Scenario:
          Given I have a model
          When I call the function
          Then I get a result
        """)
        @llm_func(1)
        fnHandler(args: ArgumentsModelName): void;
       </correct-example>
      `,
    });
  }
}

export function $scenario(target, gherkin) {}
