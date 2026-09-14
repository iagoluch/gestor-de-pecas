#INCLUDE "TOTVS.CH"
#INCLUDE "RestFul.ch"
#INCLUDE "FWADAPTEREAI.CH"

/*
+---------------------------------------------------------------------------+
!                          FICHA TECNICA DO PROGRAMA                        !
+---------------------------------------------------------------------------+
!Programa         ! GPOPSYNC                                                 !
+-----------------+---------------------------------------------------------+
!Descricao        ! API REST que devolve, sob demanda, o ProductionOrder     !
!                 ! OFICIAL de uma Ordem de Producao ao Gestor de Pecas.     !
+-----------------+---------------------------------------------------------+
!Autor            ! Gestor de Pecas - Etapa 6.2                              !
+-----------------+---------------------------------------------------------+
!Data de Criacao  ! 09/2026                                                  !
+-----------------+---------------------------------------------------------+
*/

/*/{Protheus.doc} GPOPSync
Adaptador REST. NAO monta XML, NAO le SC2/SG2/SHY para construir mensagem e
NAO inventa roteiro, ActivityDescription ou recurso. Ele apenas:

   1. valida a entrada;
   2. prepara empresa/filial no padrao GTS (SM0 + cFilAnt + cNumEmp);
   3. posiciona a SC2 na OP;
   4. chama o adapter OFICIAL de Mensagem Unica MATI650 em TRANS_SEND, com as
      MESMAS variaveis de controle usadas pela cadeia oficial;
   5. devolve o XML produzido pelo Protheus e restaura o ambiente.

Cadeia oficial reaproveitada (fontes 12.1.2510):

   PCPA111.prw::sincOP()       posiciona SC2 -> mata650PPI(,,.T.,.T.,.F.,.F.)
   mata650.prx::mata650PPI()   -> PCPa650PPI()
   pcpxfun.prx::PCPa650PPI()   define lRunPPI/cPonteiro/INCLUI/ALTERA e chama
                                  aRetXML := MATI650("", TRANS_SEND, EAI_MESSAGE_BUSINESS, "2.004")
                                  aRetXML[2] := EncodeUTF8(aRetXML[2])
                               e SO DEPOIS transporta via PCPWebsPPI().
   MATI650.prw::MATI650()      monta e RETORNA o XML em memoria (aRet[2]).

Como MATI650 devolve a mensagem em memoria, a montagem e separavel do
transporte: chamamos MATI650 diretamente e respondemos o XML (modo INLINE),
sem PCPWebsPPI e sem os efeitos colaterais do PCPa650PPI (filtro SOE, gravacao
de C2_ROTEIRO quando vazio, geracao de pendencia e POST no PcfIntegService).

O trecho TRANS_SEND do MATI650 e montagem pura: nao ha RecLock, MsUnLock,
dbDelete nem transacao. O servico e funcionalmente somente leitura - nao altera
SC2, SG2, SH6, SD3, nao aponta producao e nao movimenta estoque.

PE PCPXFUNPPI: e consultado apenas por PCPIntgPPI (pcpxfun.prx), que decide se
a integracao com o MES esta ativa para a tabela/filial (SOD->OD_ATIVO). Nao e
consultado pelo MATI650 e nao altera a montagem do ProductionOrder. A versao
GTS retorna .F. somente com U_GTS10A05 na pilha, o que nunca ocorre nesta
thread REST. Por isso o PE nao impacta este endpoint.

@type    Function
@since   02/09/2026
@version 12.1.2510
/*/
User Function GPOPSync()
Return

//-------------------------------------------------------------------------------------------------
WSRESTFUL gestorpecaspo DESCRIPTION "Gestor de Pecas - ProductionOrder sob demanda" FORMAT APPLICATION_JSON

    WSMETHOD POST PRODORDER ;
        DESCRIPTION "Gera e retorna o ProductionOrder oficial de uma OP" ;
        WSSYNTAX "/gestorpecas/v1/production-order" ;
        PATH "/gestorpecas/v1/production-order"

END WSRESTFUL

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} POST PRODORDER
Recebe {"companyId","branchId","number"} e devolve o TOTVSMessage/ProductionOrder.

   200 text/xml           - TOTVSMessage gerado pelo Protheus
   400 application/json   - requisicao invalida (SetRestFault)
   404 application/json   - status notFound - ausencia funcional, nao falha
   409 application/json   - empresa diferente da empresa da publicacao
   500 application/json   - falha inesperada da rotina Protheus, sem stack

Autenticacao e do framework REST do ambiente. Este fonte nao implementa
autenticacao propria e nao contem credencial.
/*/
//-------------------------------------------------------------------------------------------------
WSMETHOD POST PRODORDER WSRESTFUL gestorpecaspo

    Local oBody   := JsonObject():New()
    Local cErrJs  := ""
    Local cEmp    := ""
    Local cFil    := ""
    Local cNumOP  := ""
    Local cXml    := ""
    Local cErrMsg := ""
    Local nStatus := 200
    Local lRet    := .T.

    cErrJs := oBody:FromJson(::GetContent())

    If cErrJs != Nil
        FreeObj(oBody)
        SetRestFault(400, EncodeUTF8("Corpo JSON invalido."))
        Return .F.
    EndIf

    cEmp   := GPOPStr(oBody, "companyId")
    cFil   := GPOPStr(oBody, "branchId")
    cNumOP := GPOPStr(oBody, "number")
    FreeObj(oBody)
    oBody  := Nil

    // A OP pode ser alfanumerica. Nao converter para numero, nao remover zeros
    // e nao alterar a caixa: apenas espacos das pontas.
    cNumOP := AllTrim(cNumOP)
    cEmp   := AllTrim(cEmp)
    cFil   := AllTrim(cFil)

    If Empty(cNumOP)
        SetRestFault(400, EncodeUTF8("Campo number e obrigatorio."))
        Return .F.
    EndIf
    If Empty(cFil)
        SetRestFault(400, EncodeUTF8("Campo branchId e obrigatorio."))
        Return .F.
    EndIf
    If Len(cNumOP) > GPOPTam()
        SetRestFault(400, EncodeUTF8("Campo number excede o tamanho da OP no dicionario."))
        Return .F.
    EndIf

    // Trocar de EMPRESA dentro da thread HTTP exigiria reabrir dicionario e
    // tabelas. O servico atende a empresa do ambiente publicado e recusa,
    // explicitamente, uma empresa diferente - em vez de responder dados da
    // empresa errada.
    If !Empty(cEmp) .And. cEmp != AllTrim(cEmpAnt)
        SetRestFault(409, EncodeUTF8("Empresa nao atendida por esta publicacao."))
        Return .F.
    EndIf

    nStatus := GPOPBuild(cEmp, cFil, cNumOP, @cXml, @cErrMsg)

    Do Case
        Case nStatus == 200
            ::SetContentType("text/xml; charset=utf-8")
            ::SetStatus(200)
            ::SetResponse(cXml)
            lRet := .T.

        Case nStatus == 404
            // Ausencia funcional normal: nao e falha, entao nao usa SetRestFault.
            ::SetContentType(APPLICATION_JSON)
            ::SetStatus(404)
            ::SetResponse(GPOPNotFnd())
            lRet := .T.

        Case nStatus == 400
            SetRestFault(400, EncodeUTF8("Filial inexistente no cadastro de empresas."))
            lRet := .F.

        OtherWise
            SetRestFault(500, EncodeUTF8("Falha ao gerar o ProductionOrder."))
            lRet := .F.
    EndCase

    cXml := ""

Return lRet

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPBuild
Prepara ambiente, posiciona a SC2 e obtem o ProductionOrder pelo MATI650.

Todo o estado e Local/Private da requisicao. Nao existe variavel global mutavel
guardando OP, filial ou XML, de modo que chamadas concorrentes - filiais
diferentes ou a mesma OP - nao vazam contexto entre si.

@param cEmp    , Caracter, Codigo da empresa
@param cFil    , Caracter, Filial da OP
@param cNumOP  , Caracter, OP completa (C2_NUM+C2_ITEM+C2_SEQUEN)
@param cXmlOut , Caracter, [REF] XML gerado
@param cErrOut , Caracter, [REF] Mensagem tecnica para log interno
@return nStatus, Numerico, 200 | 400 | 404 | 500
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPBuild(cEmp, cFil, cNumOP, cXmlOut, cErrOut)

    Local aArea     := GetArea()
    Local aAreaSC2  := Nil
    Local aAreaEmp  := Nil
    Local cFunBkp   := FunName()
    Local cKey      := ""
    Local aRetXml   := {}
    Local nStatus   := 500
    Local bError    := Nil
    Local lOpenSM0  := .F.
    Local lOpenSC2  := .F.

    // ErrorBlock proprio: nao dependemos de wspcpexecp (Function do RPO padrao,
    // acessivel, porem interna ao fonte TOTVS e com disarmTransaction que aqui
    // nao faz sentido). Assim nao ha dependencia descoberta so em runtime.
    Private lGPOPErr := .F.
    Private cGPOPMsg := ""

    // Variaveis de controle lidas por PCPa650PPI/MATI650. Private da
    // requisicao: liberadas no retorno desta funcao.
    Private lRunPPI   := .T.   // faz MATI650 ligar lIntegPPI e chamar completXml
    Private cPonteiro := "SC2" // le do registro posicionado, nao de M->
    Private INCLUI    := .F.
    Private ALTERA    := .T.   // INCLUI/ALTERA definem Event = upsert

    Default cEmp    := ""
    Default cXmlOut := ""
    Default cErrOut := ""

    bError := ErrorBlock({|e| GPOPCatch(e)})

    BEGIN SEQUENCE

        // A thread HTTPREST possui o ambiente Protheus, mas nao garante que
        // aliases de negocio estejam abertos. SM0 deve ser aberta pelo helper
        // oficial; nunca por DBUseArea.
        If Select("SM0") == 0
            lOpenSM0 := .T.
            OpenSm0(, .F.)
        EndIf

        If Select("SM0") == 0
            cErrOut := "nao foi possivel abrir SM0 na thread REST"
            BREAK
        EndIf

        // Padrao GTS de ambiente (GTSxFUN.PRW / WS_GTS_SC7.prw): guarda SM0,
        // cFilAnt e cNumEmp; posiciona SM0; ajusta cFilAnt e cNumEmp; restaura
        // tudo no final. Implementado localmente porque U_fGoEmp mora em
        // "Nao Compilar - Producao" e sua presenca no RPO nao e garantida.
        aAreaEmp := GPOPGetEmp()

        If !GPOPGoEmp(If(Empty(cEmp), cEmpAnt, cEmp), cFil)
            nStatus := 400
            cErrOut := "filial inexistente em SM0"
            BREAK
        EndIf

        // Com empresa/filial ja posicionadas, garante a abertura logica da SC2
        // usando o helper Protheus. Nao reinicializa o ambiente REST.
        If Select("SC2") == 0
            lOpenSC2 := .T.
            ChkFile("SC2")
        EndIf

        If Select("SC2") == 0
            cErrOut := "nao foi possivel abrir SC2 na thread REST"
            BREAK
        EndIf

        aAreaSC2 := SC2->(GetArea())

        cKey := PadR(cNumOP, GPOPTam())

        SC2->(dbSetOrder(1)) // C2_FILIAL+C2_NUM+C2_ITEM+C2_SEQUEN
        If !SC2->(dbSeek(xFilial("SC2") + cKey, .F.)) .Or. SC2->(Deleted())
            nStatus := 404
            BREAK
        EndIf

        // Confirma a identidade exata, sem aceitar casamento parcial de chave.
        If SC2->(C2_NUM + C2_ITEM + C2_SEQUEN) != cKey
            nStatus := 404
            BREAK
        EndIf

        // completXml usa FunName() em Product name. A mensagem homologada pelo
        // Gestor traz MATA650: reproduzimos o mesmo valor.
        SetFunName("MATA650")

        // ADAPTER OFICIAL. Retorna {lOk, cXml, "PRODUCTIONORDER"}.
        aRetXml := MATI650("", TRANS_SEND, EAI_MESSAGE_BUSINESS, "2.004")

        If Len(aRetXml) >= 2 .And. aRetXml[1] .And. !Empty(aRetXml[2])
            // Mesmo tratamento de codificacao aplicado por PCPa650PPI antes do
            // envio: sem ele, descricoes acentuadas sairiam fora de UTF-8.
            cXmlOut := EncodeUTF8(aRetXml[2])
            nStatus := 200
        Else
            cErrOut := "MATI650 nao retornou XML"
            If Len(aRetXml) >= 2 .And. ValType(aRetXml[2]) == "C"
                cErrOut := "MATI650: " + aRetXml[2]
            EndIf
            nStatus := 500
        EndIf

    RECOVER

        If nStatus == 500 .And. !Empty(cGPOPMsg)
            cErrOut := cGPOPMsg
        EndIf

    END SEQUENCE

    ErrorBlock(bError)
    SetFunName(cFunBkp)

    // Restaura primeiro o contexto de empresa/filial enquanto SM0 ainda existe.
    If aAreaEmp != Nil .And. Select("SM0") > 0
        GPOPRestEmp(aAreaEmp)
    EndIf

    // Fecha somente aliases que esta requisicao abriu. Se ja existiam,
    // apenas restaura a area original.
    If lOpenSC2
        If Select("SC2") > 0
            SC2->(dbCloseArea())
        EndIf
    ElseIf aAreaSC2 != Nil .And. Select("SC2") > 0
        SC2->(RestArea(aAreaSC2))
    EndIf

    If lOpenSM0
        If Select("SM0") > 0
            SM0->(dbCloseArea())
        EndIf
    EndIf

    RestArea(aArea)

    If nStatus >= 400 .And. !Empty(cErrOut)
        // Diagnostico tecnico fica no log do servidor, nunca na resposta HTTP.
        ConOut("[GESTORPECASPO] OP " + cNumOP + " filial " + cFil + ": " + cErrOut)
    EndIf

Return nStatus

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPGetEmp
Guarda o contexto de empresa/filial. Equivalente local de U_fGetEmp (padrao GTS).
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPGetEmp()

    Local aAreaEmp := {}

    aAdd(aAreaEmp, SM0->(Recno()))
    aAdd(aAreaEmp, cFilAnt)
    aAdd(aAreaEmp, cNumEmp)

Return aAreaEmp

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPGoEmp
Prepara empresa/filial. Equivalente local de U_fGoEmp (padrao GTS), com a
validacao que o helper corporativo nao faz: se a filial nao existir em SM0,
devolve .F. em vez de seguir com contexto invalido.

@return lOk, Logico, .T. quando SM0 foi posicionada na empresa/filial pedidas
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPGoEmp(cEmp, cFil)

    Local aArea := GetArea()
    Local lOk   := .F.

    SM0->(dbSetOrder(1))
    If SM0->(dbSeek(SubStr(cEmp, 1, 2) + cFil))
        cFilAnt := cFil
        cNumEmp := SM0->M0_CODIGO + SM0->M0_CODFIL
        lOk     := .T.
    EndIf

    RestArea(aArea)

Return lOk

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPRestEmp
Restaura o contexto de empresa/filial. Equivalente local de U_fRestEmp (GTS).
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPRestEmp(aAreaEmp)

    Local aArea := GetArea()

    SM0->(dbGoTo(aAreaEmp[1]))
    cFilAnt := aAreaEmp[2]
    cNumEmp := aAreaEmp[3]

    RestArea(aArea)

Return Nil

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPCatch
ErrorBlock minimo da requisicao: registra o diagnostico e desvia para o RECOVER.
Nada disso chega ao cliente.
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPCatch(oError)

    lGPOPErr := .T.
    cGPOPMsg := AllTrim(oError:Description)

    ConOut("[GESTORPECASPO] " + cGPOPMsg + CHR(10) + AllTrim(oError:ErrorStack))

    BREAK

Return Nil

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPNotFnd
Corpo JSON da ausencia funcional. Isolado para nao misturar aspas no metodo.
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPNotFnd()

    Local oJson  := JsonObject():New()
    Local cJson  := ""

    oJson["status"] := "notFound"
    cJson := oJson:ToJson()

    FreeObj(oJson)
    oJson := Nil

Return cJson

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPTam
Tamanho da OP completa segundo o dicionario, sem tamanho inventado.
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPTam()
Return GetSx3Cache("C2_NUM", "X3_TAMANHO") + ;
       GetSx3Cache("C2_ITEM", "X3_TAMANHO") + ;
       GetSx3Cache("C2_SEQUEN", "X3_TAMANHO")

//-------------------------------------------------------------------------------------------------
/*/{Protheus.doc} GPOPStr
Le uma chave string do corpo JSON sem depender da caixa informada pelo cliente.
/*/
//-------------------------------------------------------------------------------------------------
Static Function GPOPStr(oBody, cKey)

    Local cValue := ""
    Local xValue := Nil
    Local aNames := {}
    Local nPos   := 0

    If oBody == Nil
        Return cValue
    EndIf

    aNames := oBody:GetNames()
    nPos   := aScan(aNames, {|x| Lower(AllTrim(x)) == Lower(cKey)})

    If nPos > 0
        xValue := oBody[aNames[nPos]]
        If ValType(xValue) == "C"
            cValue := xValue
        ElseIf xValue != Nil
            cValue := cValToChar(xValue)
        EndIf
    EndIf

Return cValue
